"""Lazy, thread-safe local embedding service with graceful degradation."""

from __future__ import annotations

import os
import threading
from typing import Optional, Sequence

MODEL_NAME = os.environ.get("TACIT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge-family convention
EMBED_DIM = 384
BATCH_SIZE = 64


class EmbeddingService:
    """Singleton service wrapping ONNX-based fastembed TextEmbedding."""

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._load_lock = threading.Lock()

    @classmethod
    def get(cls) -> "EmbeddingService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load(self) -> None:
        if self._model is not None or self._failed:
            return
        with self._load_lock:
            if self._model is not None or self._failed:
                return
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(MODEL_NAME)
            except Exception as e:
                self._failed = True
                # Graceful degradation - log and continue in keyword-only mode
                pass

    @property
    def available(self) -> bool:
        self._load()
        return self._model is not None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """For MEMORY CONTENT. No query prefix. Batched and normalized."""
        if not texts:
            return []
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
        """For SEARCH QUERIES ONLY. Prefix improves short-query retrieval on bge models."""
        return self.embed_documents([QUERY_PREFIX + text])[0]
