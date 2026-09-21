"""Tests for the embedding provider chain (OpenAI -> Gemini -> local ONNX).

The contract that matters: exactly one provider is used for the life of a
project, because vectors from different models are not comparable. Losing a
network call must not silently switch models and mix 1536-dim and 384-dim
vectors in one database.
"""

import json

import pytest

from src.search import embeddings as emb
from src.search.embeddings import (
    EmbeddingService,
    EmbeddingUnavailable,
    GEMINI_DIM,
    LOCAL_DIM,
    OPENAI_DIM,
    OPENAI_ENDPOINT,
)


@pytest.fixture(autouse=True)
def clean_provider(monkeypatch):
    """Every test starts with no keys and no cached provider."""
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "TACIT_OPENAI_EMBED_MODEL"):
        monkeypatch.delenv(var, raising=False)
    EmbeddingService.reset()
    yield
    EmbeddingService.reset()


@pytest.fixture
def no_local_model(monkeypatch):
    """Pretend fastembed is not installed, so tests never download a model."""
    monkeypatch.setattr(EmbeddingService, "_load", lambda self, allow_download=False: None)
    monkeypatch.setattr(EmbeddingService, "_embed_local", _fail_local)


def _fail_local(self, texts):
    raise AssertionError("local model must not be used when a remote key exists")


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def test_openai_wins_when_both_keys_are_present(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")

    service = EmbeddingService.get()

    assert service.provider == "openai"
    assert service.dimension == OPENAI_DIM
    assert service.available is True


def test_gemini_is_used_when_only_gemini_is_configured(monkeypatch, no_local_model):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")

    service = EmbeddingService.get()

    assert service.provider == "gemini"
    assert service.dimension == GEMINI_DIM


def test_local_onnx_is_the_zero_config_fallback(monkeypatch):
    """No keys and a working fastembed install must still work, offline."""
    class FakeModel:
        def embed(self, batch):
            class V:
                def tolist(self_inner):
                    return [0.1] * LOCAL_DIM
            return [V() for _ in batch]

    monkeypatch.setattr(
        EmbeddingService, "_load",
        lambda self, allow_download=False: setattr(self, "_model", FakeModel()),
    )

    service = EmbeddingService.get()

    assert service.provider == "local"
    assert service.dimension == LOCAL_DIM
    assert len(service.embed_documents(["hello"])[0]) == LOCAL_DIM


def test_no_provider_is_reported_rather_than_crashing(no_local_model):
    service = EmbeddingService.get()

    assert service.provider == "none"
    assert service.available is False
    assert service.dimension == 0
    assert "unavailable" in service.describe()


def test_embedding_without_a_provider_raises_a_clear_error(no_local_model):
    service = EmbeddingService.get()

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        service.embed_documents(["anything"])

    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_provider_is_sticky_across_calls(monkeypatch, no_local_model):
    """A later env change must not move a project onto a different model mid-flight."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    service = EmbeddingService.get()
    assert service.provider == "openai"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")

    assert service.provider == "openai", "provider must not silently switch models"


# ---------------------------------------------------------------------------
# OpenAI wire format
# ---------------------------------------------------------------------------

def test_openai_request_matches_the_embeddings_api(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({
            "object": "list",
            "data": [
                {"object": "embedding", "index": 1, "embedding": [0.2, 0.3]},
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.9]},
            ],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        })

    monkeypatch.setattr(emb.urllib.request, "urlopen", fake_urlopen)

    vectors = EmbeddingService.get().embed_documents(["first", "second"])

    assert captured["url"] == OPENAI_ENDPOINT
    assert captured["headers"]["authorization"] == "Bearer sk-test"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"] == {
        "model": "text-embedding-3-small",
        "input": ["first", "second"],
        "encoding_format": "float",
    }
    # Responses arrive out of order and must be realigned by "index".
    assert vectors == [[0.1, 0.9], [0.2, 0.3]]


def test_openai_model_is_configurable(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TACIT_OPENAI_EMBED_MODEL", "text-embedding-3-large")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"data": [{"index": 0, "embedding": [0.1]}]})

    monkeypatch.setattr(emb.urllib.request, "urlopen", fake_urlopen)
    service = EmbeddingService.get()
    service.embed_documents(["x"])

    assert captured["body"]["model"] == "text-embedding-3-large"
    assert service.model_id == "text-embedding-3-large"


def test_openai_failure_raises_and_does_not_fall_back(monkeypatch, no_local_model):
    """Falling back to a different model would mix incompatible vector widths."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    slept = []
    monkeypatch.setattr(EmbeddingService, "_sleep", lambda self, s: slept.append(s))
    monkeypatch.setattr(EmbeddingService, "_respect_request_interval", lambda self: None)

    attempts = {"n": 0}

    def boom(request, timeout=None):
        attempts["n"] += 1
        raise OSError("connection reset")

    monkeypatch.setattr(emb.urllib.request, "urlopen", boom)

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        EmbeddingService.get().embed_documents(["x"])

    assert "OpenAI" in str(excinfo.value)
    # A transient network error IS retried, then given up on.
    assert attempts["n"] == emb.MAX_RETRIES + 1
    assert len(slept) == emb.MAX_RETRIES


def test_openai_truncated_response_is_rejected(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        emb.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"data": [{"index": 0, "embedding": [0.1]}]}),
    )

    with pytest.raises(EmbeddingUnavailable):
        EmbeddingService.get().embed_documents(["one", "two"])


# ---------------------------------------------------------------------------
# Rate limiting (HTTP 429) during a backfill
# ---------------------------------------------------------------------------

def _http_error(code, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return emb.urllib.error.HTTPError(
        url="https://example.invalid", code=code, msg="error", hdrs=headers, fp=None
    )


def _gemini_service(monkeypatch, urlopen, pace=True):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTKEY1234567890")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(emb.urllib.request, "urlopen", urlopen)
    slept = []
    monkeypatch.setattr(EmbeddingService, "_sleep", lambda self, s: slept.append(s))
    if not pace:
        # Isolate backoff from pacing, so the recorded sleeps are retry delays only.
        monkeypatch.setattr(EmbeddingService, "_respect_request_interval", lambda self: None)
    return EmbeddingService.get(), slept


def test_rate_limit_is_retried_and_then_succeeds(monkeypatch, no_local_model):
    """The reported failure: `tacit reindex` died on HTTP 429."""
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return FakeResponse({"embeddings": [{"values": [0.1, 0.2]}]})

    service, slept = _gemini_service(monkeypatch, flaky, pace=False)

    vectors = service.embed_documents(["one memory"])

    assert vectors == [[0.1, 0.2]]
    assert calls["n"] == 2
    assert slept, "a 429 must back off before retrying"


def test_backoff_grows_exponentially(monkeypatch, no_local_model):
    def always_429(request, timeout=None):
        raise _http_error(429)

    service, slept = _gemini_service(monkeypatch, always_429, pace=False)

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["x"])

    assert len(slept) == emb.MAX_RETRIES
    # 2, 4, 8, 16 ... plus jitter, so each wait must exceed the previous one's base.
    bases = [emb.BACKOFF_BASE * (2 ** i) for i in range(emb.MAX_RETRIES)]
    for actual, base in zip(slept, bases):
        assert base <= actual <= base * 1.25 + 0.001


def test_retry_after_header_is_honoured(monkeypatch, no_local_model):
    def always_429(request, timeout=None):
        raise _http_error(429, retry_after=7)

    service, slept = _gemini_service(monkeypatch, always_429, pace=False)

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["x"])

    assert all(7.0 <= wait <= 7.0 * 1.25 + 0.001 for wait in slept)


def test_non_retryable_errors_fail_immediately(monkeypatch, no_local_model):
    """Retrying a 401 just burns time and quota."""
    calls = {"n": 0}

    def unauthorised(request, timeout=None):
        calls["n"] += 1
        raise _http_error(401)

    service, slept = _gemini_service(monkeypatch, unauthorised, pace=False)

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["x"])

    assert calls["n"] == 1
    assert slept == []


def test_large_backfills_are_split_into_paced_requests(monkeypatch, no_local_model):
    """One 55-item request is what tripped the quota in the first place."""
    payloads = []
    times = []

    def ok(request, timeout=None):
        payloads.append(json.loads(request.data.decode("utf-8")))
        times.append(emb.time.monotonic())
        count = len(payloads[-1]["requests"])
        return FakeResponse({"embeddings": [{"values": [float(count)]} for _ in range(count)]})

    service, slept = _gemini_service(monkeypatch, ok)
    total = emb.REMOTE_BATCH_SIZE * 3 + 5

    vectors = service.embed_documents([f"memory {i}" for i in range(total)])

    assert len(payloads) == 4, "items must be split across requests"
    assert all(len(p["requests"]) <= emb.REMOTE_BATCH_SIZE for p in payloads)
    assert len(vectors) == total, "every input must come back"
    # Pacing sleeps once between requests, not before the first.
    assert len(slept) == len(payloads) - 1
    assert all(0 < wait <= emb.MIN_REQUEST_INTERVAL for wait in slept)


def test_batch_order_is_preserved(monkeypatch, no_local_model):
    def ok(request, timeout=None):
        chunk = json.loads(request.data.decode("utf-8"))["requests"]
        return FakeResponse({
            "embeddings": [{"values": [float(t["content"]["parts"][0]["text"].split()[-1])]}
                           for t in chunk]
        })

    service, _ = _gemini_service(monkeypatch, ok)

    vectors = service.embed_documents([f"m {i}" for i in range(emb.REMOTE_BATCH_SIZE + 3)])

    assert [v[0] for v in vectors] == [float(i) for i in range(emb.REMOTE_BATCH_SIZE + 3)]


def test_a_single_query_is_not_paced(monkeypatch, no_local_model):
    """A person is waiting on a search; it must not stall behind the bulk interval."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTKEY1234567890")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        emb.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"embeddings": [{"values": [0.5]}]}),
    )
    slept = []
    monkeypatch.setattr(EmbeddingService, "_sleep", lambda self, s: slept.append(s))
    service = EmbeddingService.get()
    service._last_request_at = emb.time.time()  # as if a batch just ran

    service.embed_query("connection pool")

    assert slept == []


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------

def test_gemini_key_travels_in_a_header_not_the_url(monkeypatch, no_local_model):
    """A key in the query string leaks into tracebacks, logs and proxies."""
    captured = {}

    def ok(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return FakeResponse({"embeddings": [{"values": [0.1]}]})

    service, _ = _gemini_service(monkeypatch, ok)
    service.embed_documents(["x"])

    assert "AIzaSy" not in captured["url"]
    assert "key=" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "AIzaSyTESTKEY1234567890"


def test_redact_strips_credentials_from_messages():
    assert "AIza" not in emb.redact("failed for AIzaSyAR2nDaard7nntkefopFAAyDnfPTCfOJNU")
    assert "sk-" not in emb.redact("Authorization: Bearer sk-abcdefghijklmnop")
    assert emb.redact("plain message") == "plain message"


# ---------------------------------------------------------------------------
# Query embedding
# ---------------------------------------------------------------------------

def test_local_query_embedding_uses_the_bge_prefix(monkeypatch):
    seen = {}

    class FakeModel:
        def embed(self, batch):
            seen["batch"] = list(batch)

            class V:
                def tolist(self_inner):
                    return [0.0] * LOCAL_DIM
            return [V() for _ in batch]

    monkeypatch.setattr(
        EmbeddingService, "_load",
        lambda self, allow_download=False: setattr(self, "_model", FakeModel()),
    )
    monkeypatch.setattr(EmbeddingService, "_embed_local", lambda self, texts: (
        seen.update(batch=list(texts)) or [[0.0] * LOCAL_DIM for _ in texts]
    ))

    EmbeddingService.get().embed_query("connection pool exhaustion")

    assert seen["batch"][0].startswith(emb.QUERY_PREFIX)


def test_openai_query_embedding_has_no_prefix(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"data": [{"index": 0, "embedding": [0.5]}]})

    monkeypatch.setattr(emb.urllib.request, "urlopen", fake_urlopen)
    EmbeddingService.get().embed_query("connection pool exhaustion")

    assert captured["body"]["input"] == ["connection pool exhaustion"]
