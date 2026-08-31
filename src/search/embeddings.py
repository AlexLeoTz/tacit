"""Lazy, thread-safe embedding service supporting remote Gemini API and local ONNX with graceful degradation."""

from __future__ import annotations

import json
import os
import threading
from typing import Optional, Sequence
import urllib.request

MODEL_NAME = os.environ.get("TACIT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge-family convention
EMBED_DIM = 384
GEMINI_EMBED_DIM = 768
BATCH_SIZE = 64


class EmbeddingService:
    """Singleton service wrapping Gemini API or ONNX-based fastembed TextEmbedding."""

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._load_lock = threading.Lock()
        self._gemini_api_key = os.environ.get("GEMINI_API_KEY")

    @classmethod
    def get(cls) -> "EmbeddingService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _get_gemini_api_key(self) -> Optional[str]:
        return os.environ.get("GEMINI_API_KEY") or self._gemini_api_key

    def _embed_gemini(self, texts: Sequence[str], is_query: bool = False) -> Optional[list[list[float]]]:
        """Embed texts using Gemini text-embedding-004 REST API."""
        api_key = self._get_gemini_api_key()
        if not api_key:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key={api_key}"
        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"

        requests = [
            {
                "model": "models/text-embedding-004",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
            }
            for t in texts
        ]

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps({"requests": requests}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    embeddings = [item["values"] for item in data.get("embeddings", [])]
                    if len(embeddings) == len(texts):
                        return embeddings
        except Exception:
            pass
        return None

    def _load(self) -> None:
        if self._model is not None or self._failed:
            return
        with self._load_lock:
            if self._model is not None or self._failed:
                return
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(MODEL_NAME)
            except Exception:
                self._failed = True
                pass

    @property
    def available(self) -> bool:
        if self._get_gemini_api_key():
            return True
        self._load()
        return self._model is not None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """For MEMORY CONTENT. Batched and normalized."""
        if not texts:
            return []

        # 1. Try Gemini remote API if key is configured
        if self._get_gemini_api_key():
            res = self._embed_gemini(texts, is_query=False)
            if res is not None:
                return res

        # 2. Fall back to local CPU ONNX model
        self._load()
        if self._model is None:
            raise RuntimeError("Embedding backend unavailable")
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            embeddings = self._model.embed(batch)
            out.extend(v.tolist() for v in embeddings)
        return out

    def embed_query(self, text: str) -> list[float]:
        """For SEARCH QUERIES ONLY."""
        if self._get_gemini_api_key():
            res = self._embed_gemini([text], is_query=True)
            if res is not None and len(res) > 0:
                return res[0]

        return self.embed_documents([QUERY_PREFIX + text])[0]

