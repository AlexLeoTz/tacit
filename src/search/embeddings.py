"""Embedding service: a hosted, single-provider contract built around Gemini.

Provider chain, resolved once per process:

1. **Gemini** (``GEMINI_API_KEY``) — ``gemini-embedding-001``, 768 dims by
   default. This is the default engine: it is dramatically more accurate than a
   tiny offline ONNX model, and it is what makes conceptual search work across
   titles, summaries and tags.
2. **OpenAI** (``OPENAI_API_KEY``) — ``text-embedding-3-small``, 1536 dims. Kept
   as an optional alternative for shops that already standardised on OpenAI. Set
   ``TACIT_EMBED_PROVIDER=openai`` when both keys exist and OpenAI should win.

The local ONNX provider was removed deliberately. ``BAAI/bge-small-en-v1.5``
runs offline, but a 384-dimension model trained on short English passages matched
Tacit's terse engineering notes unreliably, and a missing/corrupt model cache
turned search into a multi-second retry storm. Semantic search is now a hosted
call with an explicit key; when no key is present Tacit still answers with BM25
keyword search instead of pretending the vector channel exists.

Only *titles, tags and summaries* are embedded, never full content. Vectors from
different models are not comparable, so the provider is deliberately sticky: a
network failure does **not** silently fall back to another model mid-project,
because that would mix 768-dim and 1536-dim vectors in one database. Failures
surface as :class:`EmbeddingUnavailable` and callers degrade to keyword search.

Switching providers is therefore a deliberate act that requires re-embedding:

    tacit reindex --force
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Optional, Sequence
import urllib.error
import urllib.request

#: Google Gemini. ``gemini-embedding-001`` outputs 3072 dimensions by default;
#: Tacit asks for 768 explicitly (Google's recommended size for storage/quality)
#: and normalises the truncated vector itself, as that model requires.
GEMINI_MODEL = os.environ.get("TACIT_GEMINI_MODEL", "gemini-embedding-001")
GEMINI_DIM = 768
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"

#: OpenAI (optional alternative; Gemini wins when both keys are present).
OPENAI_MODEL = os.environ.get("TACIT_OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_DIM = 1536
OPENAI_ENDPOINT = "https://api.openai.com/v1/embeddings"

#: Items sent per remote request. Google counts every item against the embedding
#: quota, so a single 55-item batch is what produced `HTTP 429 Too Many Requests`
#: during `tacit reindex`. Splitting the batch keeps each request small.
REMOTE_BATCH_SIZE = int(os.environ.get("TACIT_EMBED_BATCH_SIZE", "20"))

#: Minimum seconds between remote requests. Large backfills are paced rather
#: than fired as fast as the network allows.
MIN_REQUEST_INTERVAL = float(os.environ.get("TACIT_EMBED_MIN_INTERVAL", "2.0"))

#: Retry policy for 429 / 5xx / network failures during a remote embed.
#: Four retries at 2/4/8/16s bounds the worst case at ~30s, so an interactive
#: `memory_add` cannot hang for a minute waiting on a rate limit. Backfills are
#: resumable, so a bounded give-up is cheap.
MAX_RETRIES = int(os.environ.get("TACIT_EMBED_MAX_RETRIES", "4"))
BACKOFF_BASE = 2.0
BACKOFF_MAX = 30.0

REQUEST_TIMEOUT = 20.0

#: Anything that looks like an API key, stripped from messages we surface.
_KEY_PATTERN = re.compile(r"(AIza[0-9A-Za-z_\-]{10,}|sk-[0-9A-Za-z_\-]{10,}|Bearer\s+\S+)")


def _openai_model() -> str:
    """Read at call time so the model can be reconfigured without a reimport."""
    return os.environ.get("TACIT_OPENAI_EMBED_MODEL", OPENAI_MODEL)


def _gemini_model() -> str:
    return os.environ.get("TACIT_GEMINI_MODEL", GEMINI_MODEL)


def gemini_dim() -> int:
    """Output width requested from Gemini, or ``0`` for the model's native width.

    ``gemini-embedding-001`` natively emits 3072 dimensions; asking for 768 keeps
    the store small and matches Google's recommended storage/quality trade-off.
    Legacy models (``text-embedding-004``) reject the field, so it is only sent
    when explicitly configured or when the model is one of the MRL embedding
    models.
    """
    raw = os.environ.get("TACIT_GEMINI_DIM", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return GEMINI_DIM
        return value if 1 <= value <= 3072 else GEMINI_DIM
    return GEMINI_DIM if _gemini_model().startswith("gemini-embedding") else 0


class EmbeddingUnavailable(RuntimeError):
    """Raised when the resolved embedding provider cannot serve a request."""


def redact(text: str) -> str:
    """Strip anything resembling a credential from a user-facing message."""
    return _KEY_PATTERN.sub("***REDACTED***", text)


def body_message(raw: str) -> str:
    """Pull a human-readable reason out of an error body, whatever its shape.

    Every provider hides the reason in the body rather than the status line:

    * Google  ``{"error": {"code": 400, "message": "...", "status": "INVALID_ARGUMENT"}}``
    * OpenAI  ``{"error": {"message": "...", "type": "invalid_request_error", "code": "..."}}``
    * generic ``{"message": ...}``, ``{"detail": ...}`` or plain text
    """
    if not raw.strip():
        return ""

    try:
        payload = json.loads(raw)
    except ValueError:
        return " ".join(raw.split())[:300]

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or ""
            qualifiers = [
                str(error[key]) for key in ("status", "type", "code") if error.get(key)
            ]
            if message:
                return f"[{'/'.join(qualifiers)}] {message}" if qualifiers else str(message)
        if isinstance(error, str) and error:
            return error
        for key in ("message", "detail", "error_description"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return " ".join(raw.split())[:300]


def error_detail(exc: Exception) -> str:
    """Extract the provider's own explanation from an HTTP error.

    Google answers an invalid API key with ``HTTP 400 Bad Request`` and puts the
    actual reason only in the JSON body (``API key not valid``), so surfacing
    ``str(exc)`` alone tells the user nothing actionable.
    """
    if not isinstance(exc, urllib.error.HTTPError):
        return f"{type(exc).__name__}: {exc}"

    reason = getattr(exc, "reason", "") or ""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""

    detail = body_message(raw)
    return f"HTTP {exc.code} {reason}".strip() + (f": {detail}" if detail else "")


#: Fragments that mean "the credential was refused", across provider wordings.
_AUTH_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "incorrect api key",
    "invalid api key",
    "unauthenticated",
    "permission denied",
    "permission_denied",
)

#: Fragments that mean "you are out of allowance", not "your request is wrong".
_QUOTA_MARKERS = ("quota", "rate limit", "rate_limit", "too many requests", "billing")


def remediation_hint(provider: str, detail: str) -> str:
    """Turn a provider error into something the user can act on."""
    lowered = detail.lower()

    if any(marker in lowered for marker in _AUTH_MARKERS):
        variable = "OPENAI_API_KEY" if provider == "OpenAI" else "GEMINI_API_KEY"
        return (
            f"\nHint: the provider rejected the credential Tacit sent. Check that {variable} is set "
            "in THIS shell (a revoked or stale key may still be exported), that the key is still "
            "active, and that the embeddings API is enabled for its project."
        )

    if any(marker in lowered for marker in _QUOTA_MARKERS):
        return (
            "\nHint: this is an allowance limit, not a bad request. Wait for the quota window to "
            "reset, or slow the backfill down with TACIT_EMBED_MIN_INTERVAL (seconds between "
            "requests) and TACIT_EMBED_BATCH_SIZE (items per request)."
        )

    return ""


class EmbeddingService:
    """Singleton service resolving one embedding provider for the whole process."""

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()

    def __init__(self, project_root=None) -> None:
        # ``project_root`` is accepted for backwards compatibility; hosted
        # providers do not need a model cache inside the project.
        self._project_root = project_root
        self._failed = False
        self._last_error = ""
        self._last_request_at: Optional[float] = None
        self._openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self._observed_dim = 0
        #: Resolved once. Vectors from different models are not comparable, so a
        #: key appearing/disappearing mid-session must never move a project onto
        #: another embedding space; `reset()` is the deliberate switch.
        self._resolved_provider: Optional[str] = None

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
        """Resolve the provider: Gemini by default, OpenAI as an opt-in alternative.

        ``allow_download`` is accepted for API compatibility with older callers;
        there is no local model left to download.
        """
        if self._resolved_provider is not None:
            return self._resolved_provider
        explicit = os.environ.get("TACIT_EMBED_PROVIDER", "").strip().lower()
        if explicit == "openai" and self._openai_key():
            provider = "openai"
        elif self._gemini_key():
            provider = "gemini"
        elif self._openai_key():
            provider = "openai"
        else:
            provider = "none"
        self._resolved_provider = provider
        return provider

    @property
    def provider(self) -> str:
        """One of ``gemini``, ``openai`` or ``none``."""
        return self._resolve_provider()

    @property
    def available(self) -> bool:
        """True when a provider can serve a query right now."""
        return self._resolve_provider() != "none"

    @property
    def last_error(self) -> str:
        """Why the last remote call failed, for user-facing messages."""
        return self._last_error

    def key_hint(self) -> str:
        """Masked fingerprint of the credential in use, for local diagnosis.

        Shows enough to tell *which* key the process is actually holding — the
        usual cause of a rejected key is a revoked one still exported in the
        shell that launched the command.
        """
        provider = self._resolve_provider()
        if provider == "gemini":
            key = self._gemini_key()
        elif provider == "openai":
            key = self._openai_key()
        else:
            key = self._gemini_key() or self._openai_key()
        if not key:
            return "none"
        if len(key) <= 12:
            return "***"
        return f"{key[:6]}...{key[-4:]}"

    @property
    def dimension(self) -> int:
        """Vector width of the resolved provider (0 when unavailable)."""
        provider = self._resolve_provider()
        if provider == "gemini":
            return gemini_dim() or self._observed_dim or 768
        if provider == "openai":
            return OPENAI_DIM
        return 0

    @property
    def model_id(self) -> str:
        """Identifier stored alongside vectors so mixed models can be detected."""
        return {
            "openai": _openai_model(),
            "gemini": _gemini_model(),
        }.get(self._resolve_provider(), "none")

    def describe(self) -> str:
        provider = self._resolve_provider()
        if provider == "none":
            detail = f" ({self._last_error})" if self._last_error else ""
            return (
                "unavailable (GEMINI_API_KEY is not set, and no OPENAI_API_KEY was found)"
                f"{detail}"
            )
        return f"{provider}:{self.model_id} ({self.dimension}d)"

    # -- remote providers --------------------------------------------------

    def _sleep(self, seconds: float) -> None:
        """Indirection so tests do not actually wait."""
        if seconds > 0:
            time.sleep(seconds)

    def _respect_request_interval(self) -> None:
        """Block until at least ``MIN_REQUEST_INTERVAL`` has passed since the last call."""
        if self._last_request_at is None:
            return
        elapsed = time.time() - self._last_request_at
        self._sleep(MIN_REQUEST_INTERVAL - elapsed)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Rate limits, server errors and network trouble are worth retrying.

        Status 400/401/403 are not: retrying them just burns quota.
        """
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code == 429 or 500 <= exc.code < 600
        return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))

    @staticmethod
    def _retry_after(exc: Exception) -> Optional[float]:
        """Honour a ``Retry-After`` header when the server sends one.

        Checks ``hdrs`` as well as ``headers``: ``HTTPError`` only populates
        ``headers`` when it was constructed with a response object, and a dict is
        passed straight through in other paths.
        """
        for attribute in ("headers", "hdrs"):
            headers = getattr(exc, attribute, None)
            if not headers:
                continue
            try:
                raw = headers.get("Retry-After")
            except AttributeError:
                continue
            if not raw:
                continue
            try:
                return max(0.0, float(str(raw).strip()))
            except ValueError:
                return None  # HTTP-date form; fall back to exponential backoff
        return None

    def _request_json(
        self,
        url: str,
        payload: dict,
        headers: dict,
        *,
        pace: bool = True,
        provider: str = "remote",
    ) -> dict:
        """POST JSON with pacing and exponential backoff on retryable failures.

        ``pace`` should be True for bulk work (reindex, batch add) and False for a
        single interactive query, where a 2-second stall would be felt.
        """
        delay = BACKOFF_BASE
        attempt = 0
        while True:
            if pace:
                self._respect_request_interval()
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self._last_request_at = time.time()
                return body
            except Exception as exc:
                self._last_request_at = time.time()
                attempt += 1
                detail = redact(error_detail(exc))
                if not self._is_retryable(exc) or attempt > MAX_RETRIES:
                    raise EmbeddingUnavailable(
                        f"{provider} embedding request failed: {detail}"
                        + remediation_hint(provider, detail)
                    ) from exc

                wait = self._retry_after(exc) or delay
                wait = min(wait, BACKOFF_MAX)
                # Jitter avoids every worker waking up at the same instant.
                wait += random.uniform(0.0, 0.25 * wait)
                self._last_error = redact(
                    f"{provider} {detail} — retry {attempt}/{MAX_RETRIES} in {wait:.1f}s"
                )
                self._sleep(wait)
                delay = min(delay * 2, BACKOFF_MAX)

    def _embed_openai(
        self, texts: Sequence[str], *, pace: bool = True
    ) -> list[list[float]]:
        """Embed via the OpenAI embeddings API, in paced batches."""
        api_key = self._openai_key()
        if not api_key:
            raise EmbeddingUnavailable("OPENAI_API_KEY is not set")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), max(1, REMOTE_BATCH_SIZE)):
            chunk = list(texts[start:start + max(1, REMOTE_BATCH_SIZE)])
            body = self._request_json(
                OPENAI_ENDPOINT,
                {"model": _openai_model(), "input": chunk, "encoding_format": "float"},
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                pace=pace,
                provider="OpenAI",
            )
            # The API returns an "index" per item; sort so results line up.
            items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
            chunk_vectors = [item.get("embedding") for item in items]
            if len(chunk_vectors) != len(chunk) or any(v is None for v in chunk_vectors):
                raise EmbeddingUnavailable("OpenAI returned an unexpected number of embeddings")
            vectors.extend(chunk_vectors)
        return vectors

    def _embed_gemini(
        self, texts: Sequence[str], is_query: bool = False, *, pace: bool = True
    ) -> list[list[float]]:
        """Embed via the Gemini REST API, in paced batches.

        Gemini's embedding models are asymmetric: ``RETRIEVAL_DOCUMENT`` for the
        stored title/tags/summary text, ``RETRIEVAL_QUERY`` for the search query.
        Sending the wrong task type costs recall, so the two paths are explicit.
        """
        api_key = self._gemini_key()
        if not api_key:
            raise EmbeddingUnavailable("GEMINI_API_KEY is not set")

        model = _gemini_model()
        # The key travels in a header, never the URL: query strings end up in
        # logs, proxies and tracebacks, which is how it escaped last time.
        url = GEMINI_ENDPOINT.format(model=model)
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        output_dim = gemini_dim()

        vectors: list[list[float]] = []
        for start in range(0, len(texts), max(1, REMOTE_BATCH_SIZE)):
            chunk = list(texts[start:start + max(1, REMOTE_BATCH_SIZE)])
            requests = []
            for text in chunk:
                item = {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]},
                }
                # gemini-embedding-2 does not accept taskType; the default model
                # (gemini-embedding-001) does and benefits from it.
                if not model.startswith("gemini-embedding-2"):
                    item["taskType"] = task_type
                if output_dim:
                    item["outputDimensionality"] = output_dim
                requests.append(item)

            body = self._request_json(
                url,
                {"requests": requests},
                headers,
                pace=pace,
                provider="Gemini",
            )
            chunk_vectors = [item.get("values") for item in body.get("embeddings", [])]
            if len(chunk_vectors) != len(chunk) or any(v is None for v in chunk_vectors):
                raise EmbeddingUnavailable("Gemini returned an unexpected number of embeddings")

            expected = self.dimension
            for values in chunk_vectors:
                if values:
                    self._observed_dim = len(values)
            if expected and any(len(v) != expected for v in chunk_vectors):
                actual = len(chunk_vectors[0])
                raise EmbeddingUnavailable(
                    f"Gemini returned {actual}-dimension vectors but Tacit expected {expected}. "
                    "Set TACIT_GEMINI_DIM to the width you want (768, 1536 or 3072) and run "
                    "`tacit reindex --force`, or use TACIT_GEMINI_MODEL=text-embedding-004."
                )
            vectors.extend(chunk_vectors)
        return vectors

    # -- public API --------------------------------------------------------

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed memory titles/tags/summaries for storage."""
        if not texts:
            return []
        provider = self._resolve_provider()
        if provider == "gemini":
            return self._embed_gemini(texts, is_query=False)
        if provider == "openai":
            return self._embed_openai(texts)
        raise EmbeddingUnavailable(
            "no embedding provider configured.\n"
            "Hint: set GEMINI_API_KEY to use Google Gemini (gemini-embedding-001), "
            "or OPENAI_API_KEY for the optional OpenAI provider. Without a key, "
            "Tacit still works, but search is keyword-only (BM25)."
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query with the same provider used for documents.

        ``pace=False``: a person is waiting, so this must not stall behind the
        2-second bulk interval. Retries still apply if the API rate-limits it.
        """
        provider = self._resolve_provider()
        if provider == "gemini":
            return self._embed_gemini([text], is_query=True, pace=False)[0]
        if provider == "openai":
            return self._embed_openai([text], pace=False)[0]
        raise EmbeddingUnavailable("no embedding provider configured")
