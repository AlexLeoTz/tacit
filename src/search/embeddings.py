"""Embedding service: pluggable providers with a strict, single-provider contract.

Provider chain, resolved once per process:

1. **OpenAI** (``OPENAI_API_KEY``) — ``text-embedding-3-small``, 1536 dims.
2. **Gemini** (``GEMINI_API_KEY``) — ``gemini-embedding-001``, 768 dims.
3. **Local ONNX** (``fastembed``) — ``BAAI/bge-small-en-v1.5``, 384 dims, offline
   and zero-config. This stays as the fallback so Tacit keeps working without a
   network or a paid key.

Only *titles, tags and summaries* are embedded, never full content. Vectors from
different models are not comparable, so the provider is deliberately sticky: a
network failure does **not** silently fall back to another model mid-project,
because that would mix 1536-dim and 384-dim vectors in one database. Failures
surface as :class:`EmbeddingUnavailable` and callers degrade to keyword search.

Switching providers is therefore a deliberate act that requires re-embedding:

    tacit reindex --force
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional, Sequence
import urllib.request

#: Local ONNX model (offline fallback).
LOCAL_MODEL = os.environ.get("TACIT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
LOCAL_DIM = 384

#: Google Gemini.
GEMINI_MODEL = os.environ.get("TACIT_GEMINI_MODEL", "gemini-embedding-001")
GEMINI_DIM = 768

#: OpenAI.
OPENAI_MODEL = os.environ.get("TACIT_OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_DIM = 1536
OPENAI_ENDPOINT = "https://api.openai.com/v1/embeddings"

#: bge-family models expect this prefix on queries only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BATCH_SIZE = 64
REQUEST_TIMEOUT = 20.0

#: Backwards-compatible alias for callers that referenced the old constant.
EMBED_DIM = LOCAL_DIM


def _openai_model() -> str:
    """Read at call time so the model can be reconfigured without a reimport."""
    return os.environ.get("TACIT_OPENAI_EMBED_MODEL", OPENAI_MODEL)


def _gemini_model() -> str:
    return os.environ.get("TACIT_GEMINI_MODEL", GEMINI_MODEL)


def _local_model() -> str:
    return os.environ.get("TACIT_EMBED_MODEL", LOCAL_MODEL)


class EmbeddingUnavailable(RuntimeError):
    """Raised when the resolved embedding provider cannot serve a request."""


class EmbeddingService:
    """Singleton service resolving one embedding provider for the whole process."""

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._load_lock = threading.Lock()
        self._provider: Optional[str] = None
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._gemini_api_key = os.environ.get("GEMINI_API_KEY")

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def get(cls) -> "EmbeddingService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the cached instance so a changed environment is picked up."""
        with cls._lock:
            cls._instance = None

    # -- provider resolution ----------------------------------------------

    def _openai_key(self) -> Optional[str]:
        return os.environ.get("OPENAI_API_KEY") or self._openai_api_key

    def _gemini_key(self) -> Optional[str]:
        return os.environ.get("GEMINI_API_KEY") or self._gemini_api_key

    def _resolve_provider(self) -> str:
        """Resolve and cache the provider: OpenAI, then Gemini, then local ONNX."""
        if self._provider is not None:
            return self._provider
        if self._openai_key():
            self._provider = "openai"
        elif self._gemini_key():
            self._provider = "gemini"
        else:
            self._load()
            self._provider = "local" if self._model is not None else "none"
        return self._provider

    @property
    def provider(self) -> str:
        """One of ``openai``, ``gemini``, ``local`` or ``none``."""
        return self._resolve_provider()

    @property
    def available(self) -> bool:
        return self._resolve_provider() != "none"

    @property
    def dimension(self) -> int:
        """Vector width of the resolved provider (0 when unavailable)."""
        return {"openai": OPENAI_DIM, "gemini": GEMINI_DIM, "local": LOCAL_DIM}.get(
            self._resolve_provider(), 0
        )

    @property
    def model_id(self) -> str:
        """Identifier stored alongside vectors so mixed models can be detected."""
        return {
            "openai": _openai_model(),
            "gemini": _gemini_model(),
            "local": _local_model(),
        }.get(self._resolve_provider(), "none")

    def describe(self) -> str:
        provider = self._resolve_provider()
        if provider == "none":
            return "unavailable (no OPENAI_API_KEY, no GEMINI_API_KEY, no local ONNX model)"
        return f"{provider}:{self.model_id} ({self.dimension}d)"

    # -- remote providers --------------------------------------------------

    def _embed_openai(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed via the OpenAI embeddings API."""
        api_key = self._openai_key()
        if not api_key:
            raise EmbeddingUnavailable("OPENAI_API_KEY is not set")

        payload = {
            "model": _openai_model(),
            "input": list(texts),
            "encoding_format": "float",
        }
        request = urllib.request.Request(
            OPENAI_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network, auth, quota, malformed JSON
            raise EmbeddingUnavailable(f"OpenAI embedding request failed: {exc}") from exc

        # The API returns an "index" per item; sort so results line up with inputs.
        items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in items]
        if len(vectors) != len(texts) or any(v is None for v in vectors):
            raise EmbeddingUnavailable("OpenAI returned an unexpected number of embeddings")
        return vectors

    def _embed_gemini(self, texts: Sequence[str], is_query: bool = False) -> list[list[float]]:
        """Embed via the Gemini REST API."""
        api_key = self._gemini_key()
        if not api_key:
            raise EmbeddingUnavailable("GEMINI_API_KEY is not set")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{_gemini_model()}:batchEmbedContents?key={api_key}"
        )
        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        payload = {
            "requests": [
                {
                    "model": f"models/{_gemini_model()}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                }
                for text in texts
            ]
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise EmbeddingUnavailable(f"Gemini embedding request failed: {exc}") from exc

        vectors = [item.get("values") for item in body.get("embeddings", [])]
        if len(vectors) != len(texts) or any(v is None for v in vectors):
            raise EmbeddingUnavailable("Gemini returned an unexpected number of embeddings")
        return vectors

    # -- local provider ----------------------------------------------------

    def _load(self) -> None:
        if self._model is not None or self._failed:
            return
        with self._load_lock:
            if self._model is not None or self._failed:
                return
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(_local_model())
            except Exception:
                self._failed = True

    def _embed_local(self, texts: Sequence[str]) -> list[list[float]]:
        self._load()
        if self._model is None:
            raise EmbeddingUnavailable("local ONNX embedding model is not installed")
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start:start + BATCH_SIZE]
            out.extend(vector.tolist() for vector in self._model.embed(batch))
        return out

    # -- public API --------------------------------------------------------

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed memory titles/tags/summaries for storage."""
        if not texts:
            return []
        provider = self._resolve_provider()
        if provider == "openai":
            return self._embed_openai(texts)
        if provider == "gemini":
            return self._embed_gemini(texts, is_query=False)
        if provider == "local":
            return self._embed_local(texts)
        raise EmbeddingUnavailable(
            "no embedding provider configured: set OPENAI_API_KEY or GEMINI_API_KEY, "
            "or install the local model with `pip install fastembed`"
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query with the same provider used for documents."""
        provider = self._resolve_provider()
        if provider == "openai":
            return self._embed_openai([text])[0]
        if provider == "gemini":
            return self._embed_gemini([text], is_query=True)[0]
        if provider == "local":
            # Asymmetric retrieval: only the query side takes the bge prefix.
            return self._embed_local([QUERY_PREFIX + text])[0]
        raise EmbeddingUnavailable("no embedding provider configured")
