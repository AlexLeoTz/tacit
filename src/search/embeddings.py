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
from pathlib import Path
import sys
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


def user_cache_dir() -> Path:
    """Persistent per-user cache location for downloaded models."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), "AppData", "Local")
        return Path(base) / "tacit" / "models"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tacit" / "models"


def _is_writable_dir(path: Path) -> bool:
    """True when we can actually create files in ``path``."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".tacit_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_cache_dir(project_root: Optional[Path] = None) -> Path:
    """Pick a persistent, writable directory for the ONNX model.

    fastembed's own default is the OS temp directory, which is a poor choice for
    a ~50 MB download: it can vanish between runs, and sandboxes frequently deny
    writes there — the failure surfaced as a multi-second retry storm ending in
    ``Permission denied`` and a search timeout.

    Order: explicit override, then the per-user cache, then ``.tacit/models``
    inside the project (the only location guaranteed writable inside a
    workspace-restricted sandbox).
    """
    override = os.environ.get("TACIT_EMBED_CACHE") or os.environ.get("FASTEMBED_CACHE_PATH")
    if override:
        candidate = Path(override).expanduser()
        if _is_writable_dir(candidate):
            return candidate
        return candidate

    if project_root is None:
        try:
            from ..utils.config import Config

            project_root = Config.find_project_root()
        except Exception:
            project_root = None

    candidates = [user_cache_dir()]
    if project_root is not None:
        candidates.append(Path(project_root) / ".tacit" / "models")

    for candidate in candidates:
        if _is_writable_dir(candidate):
            return candidate
    return candidates[-1]


class EmbeddingUnavailable(RuntimeError):
    """Raised when the resolved embedding provider cannot serve a request."""


class EmbeddingService:
    """Singleton service resolving one embedding provider for the whole process."""

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._model = None
        self._failed = False
        self._load_lock = threading.Lock()
        self._cache_dir: Optional[Path] = None
        self._last_error = ""
        self._project_root = project_root
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

    def _resolve_provider(self, allow_download: bool = False) -> str:
        """Resolve the provider: OpenAI, then Gemini, then local ONNX.

        ``allow_download=False`` (the default, used by every read path) only
        accepts a model that is already on disk. A search query must never block
        on a 50 MB download: fetching a model is an explicit action, performed by
        ``tacit reindex``.
        """
        if self._openai_key():
            return "openai"
        if self._gemini_key():
            return "gemini"
        self._load(allow_download=allow_download)
        return "local" if self._model is not None else "none"

    @property
    def provider(self) -> str:
        """One of ``openai``, ``gemini``, ``local`` or ``none``."""
        return self._resolve_provider()

    @property
    def available(self) -> bool:
        """True when a provider can serve a query *right now*, without downloading."""
        return self._resolve_provider() != "none"

    @property
    def cache_dir(self) -> Path:
        if self._cache_dir is None:
            self._cache_dir = resolve_cache_dir(self._project_root)
        return self._cache_dir

    @property
    def last_error(self) -> str:
        """Why the local model could not be used, for user-facing messages."""
        return self._last_error

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
            detail = f" ({self._last_error})" if self._last_error else ""
            return (
                "unavailable (no OPENAI_API_KEY, no GEMINI_API_KEY, and no local ONNX "
                f"model cached in {self.cache_dir}){detail}"
            )
        return f"{provider}:{self.model_id} ({self.dimension}d)"

    def ensure_local_model(self, allow_download: bool = True) -> bool:
        """Prepare the local ONNX model, downloading it if permitted.

        Only called from explicit maintenance commands (``tacit reindex``), never
        from a query.
        """
        if self._openai_key() or self._gemini_key():
            return False
        self._load(allow_download=allow_download)
        return self._model is not None

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

    def _load(self, allow_download: bool = False) -> None:
        """Load the local ONNX model, optionally downloading it.

        ``local_files_only=True`` when downloads are not allowed makes a missing
        model fail in milliseconds instead of retrying the download three times
        with backoff — the retry storm that made `tacit search` appear to hang.
        """
        if self._model is not None:
            return
        if self._failed and not allow_download:
            return
        with self._load_lock:
            if self._model is not None:
                return
            if self._failed and not allow_download:
                return
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    _local_model(),
                    cache_dir=str(self.cache_dir),
                    local_files_only=not allow_download,
                )
                self._failed = False
                self._last_error = ""
            except Exception as exc:
                self._failed = True
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]

    def _embed_local(self, texts: Sequence[str]) -> list[list[float]]:
        self._load()
        if self._model is None:
            raise EmbeddingUnavailable(
                f"local ONNX embedding model is not available in {self.cache_dir}"
                + (f" ({self._last_error})" if self._last_error else "")
            )
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
