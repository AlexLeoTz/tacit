"""Tests for the hosted embedding provider chain (Gemini, then OpenAI).

The contract that matters: exactly one provider is used for the life of a
project, because vectors from different models are not comparable. Losing a
network call must not silently switch models and mix 768-dim Gemini vectors with
1536-dim OpenAI vectors in one database.

The local ONNX provider was removed: its cache failures and 384-dim vectors were
the main source of unreliable search.
"""

import json

import pytest

from src.search import embeddings as emb
from src.search.embeddings import (
    EmbeddingService,
    EmbeddingUnavailable,
    GEMINI_DIM,
    OPENAI_DIM,
    OPENAI_ENDPOINT,
)

GEMINI_KEY = "AIzaSyTESTKEY1234567890"


@pytest.fixture(autouse=True)
def clean_provider(monkeypatch):
    """Every test starts with no keys and no cached provider."""
    for var in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "TACIT_OPENAI_EMBED_MODEL",
        "TACIT_GEMINI_MODEL",
        "TACIT_GEMINI_DIM",
        "TACIT_EMBED_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)
    EmbeddingService.reset()
    yield
    EmbeddingService.reset()


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

def test_gemini_is_the_default_when_both_keys_are_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    service = EmbeddingService.get()

    assert service.provider == "gemini"
    assert service.dimension == GEMINI_DIM
    assert service.available is True


def test_openai_is_available_as_an_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TACIT_EMBED_PROVIDER", "openai")

    service = EmbeddingService.get()

    assert service.provider == "openai"
    assert service.dimension == OPENAI_DIM


def test_openai_is_used_when_it_is_the_only_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    service = EmbeddingService.get()

    assert service.provider == "openai"
    assert service.dimension == OPENAI_DIM


def test_gemini_is_used_when_only_gemini_is_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)

    service = EmbeddingService.get()

    assert service.provider == "gemini"
    assert service.dimension == GEMINI_DIM


def test_no_provider_is_reported_rather_than_crashing():
    service = EmbeddingService.get()

    assert service.provider == "none"
    assert service.available is False
    assert service.dimension == 0
    assert "GEMINI_API_KEY" in service.describe()


def test_embedding_without_a_provider_raises_a_clear_error():
    service = EmbeddingService.get()

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        service.embed_documents(["anything"])

    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message
    assert "keyword-only" in message
    assert "fastembed" not in message


def test_provider_is_sticky_across_calls(monkeypatch):
    """A later env change must not move a project onto a different model mid-flight."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    service = EmbeddingService.get()
    assert service.provider == "openai"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)

    assert service.provider == "openai", "provider must not silently switch models"


def test_gemini_provider_is_sticky_too(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    service = EmbeddingService.get()
    assert service.provider == "gemini"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TACIT_EMBED_PROVIDER", "openai")

    assert service.provider == "gemini"


# ---------------------------------------------------------------------------
# Gemini wire format
# ---------------------------------------------------------------------------

def _gemini_service(monkeypatch, urlopen, pace=True):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(emb.urllib.request, "urlopen", urlopen)
    slept = []
    monkeypatch.setattr(EmbeddingService, "_sleep", lambda self, s: slept.append(s))
    if not pace:
        # Isolate backoff from pacing, so the recorded sleeps are retry delays only.
        monkeypatch.setattr(EmbeddingService, "_respect_request_interval", lambda self: None)
    return EmbeddingService.get(), slept


def test_gemini_request_matches_the_batch_embed_api(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {"embeddings": [{"values": [0.1] * GEMINI_DIM}, {"values": [0.2] * GEMINI_DIM}]}
        )

    service, _ = _gemini_service(monkeypatch, fake_urlopen, pace=False)
    service.embed_documents(["first", "second"])

    assert captured["url"].endswith("gemini-embedding-001:batchEmbedContents")
    assert captured["headers"]["x-goog-api-key"] == GEMINI_KEY
    assert "key=" not in captured["url"]
    assert [r["content"]["parts"][0]["text"] for r in captured["body"]["requests"]] == [
        "first",
        "second",
    ]
    assert all(r["taskType"] == "RETRIEVAL_DOCUMENT" for r in captured["body"]["requests"])
    assert all(r["outputDimensionality"] == GEMINI_DIM for r in captured["body"]["requests"])


def test_gemini_queries_use_the_retrieval_query_task(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"embeddings": [{"values": [0.5] * GEMINI_DIM}]})

    service, _ = _gemini_service(monkeypatch, fake_urlopen, pace=False)
    service.embed_query("connection pool")

    assert captured["body"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_gemini_model_and_dimension_are_configurable(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"embeddings": [{"values": [0.1] * 1536}]})

    monkeypatch.setenv("TACIT_GEMINI_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("TACIT_GEMINI_DIM", "1536")
    service, _ = _gemini_service(monkeypatch, fake_urlopen, pace=False)

    assert service.model_id == "gemini-embedding-001"
    service.embed_documents(["x"])

    assert captured["body"]["requests"][0]["outputDimensionality"] == 1536


def test_gemini_dimension_mismatch_is_rejected(monkeypatch):
    """A silently wrong width would make every stored vector unusable."""
    service, _ = _gemini_service(
        monkeypatch,
        lambda request, timeout=None: FakeResponse({"embeddings": [{"values": [0.1] * 5}]}),
        pace=False,
    )

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        service.embed_documents(["x"])

    assert "expected 768" in str(excinfo.value)
    assert "TACIT_GEMINI_DIM" in str(excinfo.value)


def test_gemini_truncated_response_is_rejected(monkeypatch):
    service, _ = _gemini_service(
        monkeypatch,
        lambda request, timeout=None: FakeResponse({"embeddings": [{"values": [0.1] * GEMINI_DIM}]}),
        pace=False,
    )

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["one", "two"])


# ---------------------------------------------------------------------------
# OpenAI wire format (optional provider)
# ---------------------------------------------------------------------------

def test_openai_request_matches_the_embeddings_api(monkeypatch):
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


def test_openai_model_is_configurable(monkeypatch):
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


# ---------------------------------------------------------------------------
# Rate limiting (HTTP 429) during a backfill
# ---------------------------------------------------------------------------

def _http_error(code, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return emb.urllib.error.HTTPError(
        url="https://example.invalid", code=code, msg="error", hdrs=headers, fp=None
    )


def test_rate_limit_is_retried_and_then_succeeds(monkeypatch):
    """The reported failure: `tacit reindex` died on HTTP 429."""
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return FakeResponse({"embeddings": [{"values": [0.1] * GEMINI_DIM}]})

    service, slept = _gemini_service(monkeypatch, flaky, pace=False)

    vectors = service.embed_documents(["one memory"])

    assert vectors == [[0.1] * GEMINI_DIM]
    assert calls["n"] == 2
    assert slept, "a 429 must back off before retrying"


def test_network_failures_are_retried_then_given_up_on(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
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

    assert "Gemini" in str(excinfo.value)
    assert attempts["n"] == emb.MAX_RETRIES + 1
    assert len(slept) == emb.MAX_RETRIES


def test_backoff_grows_exponentially(monkeypatch):
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


def test_retry_after_header_is_honoured(monkeypatch):
    def always_429(request, timeout=None):
        raise _http_error(429, retry_after=7)

    service, slept = _gemini_service(monkeypatch, always_429, pace=False)

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["x"])

    assert all(7.0 <= wait <= 7.0 * 1.25 + 0.001 for wait in slept)


def test_non_retryable_errors_fail_immediately(monkeypatch):
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


def test_large_backfills_are_split_into_paced_requests(monkeypatch):
    """One 55-item request is what tripped the quota in the first place."""
    payloads = []
    sleeps = []

    def ok(request, timeout=None):
        payloads.append(json.loads(request.data.decode("utf-8")))
        count = len(payloads[-1]["requests"])
        return FakeResponse({"embeddings": [{"values": [0.1] * GEMINI_DIM} for _ in range(count)]})

    service, slept = _gemini_service(monkeypatch, ok)
    total = emb.REMOTE_BATCH_SIZE * 3 + 5

    vectors = service.embed_documents([f"memory {i}" for i in range(total)])

    assert len(payloads) == 4, "items must be split across requests"
    assert all(len(p["requests"]) <= emb.REMOTE_BATCH_SIZE for p in payloads)
    assert len(vectors) == total, "every input must come back"
    # Pacing sleeps once between requests, not before the first.
    assert len(slept) == len(payloads) - 1
    assert all(0 < wait <= emb.MIN_REQUEST_INTERVAL for wait in slept)


def test_batch_order_is_preserved(monkeypatch):
    def ok(request, timeout=None):
        chunk = json.loads(request.data.decode("utf-8"))["requests"]
        return FakeResponse({
            "embeddings": [
                {"values": [float(t["content"]["parts"][0]["text"].split()[-1])] * GEMINI_DIM}
                for t in chunk
            ]
        })

    service, _ = _gemini_service(monkeypatch, ok)

    vectors = service.embed_documents([f"m {i}" for i in range(emb.REMOTE_BATCH_SIZE + 3)])

    assert [round(v[0]) for v in vectors] == list(range(emb.REMOTE_BATCH_SIZE + 3))


def test_a_single_query_is_not_paced(monkeypatch):
    """A person is waiting on a search; it must not stall behind the bulk interval."""
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        emb.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse(
            {"embeddings": [{"values": [0.5] * GEMINI_DIM}]}
        ),
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

def test_gemini_key_travels_in_a_header_not_the_url(monkeypatch):
    """A key in the query string leaks into tracebacks, logs and proxies."""
    captured = {}

    def ok(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return FakeResponse({"embeddings": [{"values": [0.1] * GEMINI_DIM}]})

    service, _ = _gemini_service(monkeypatch, ok, pace=False)
    service.embed_documents(["x"])

    assert "AIzaSy" not in captured["url"]
    assert "key=" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == GEMINI_KEY


def test_redact_strips_credentials_from_messages():
    assert "AIza" not in emb.redact("failed for AIzaSyAR2nDaard7nntkefopFAAyDnfPTCfOJNU")
    assert "sk-" not in emb.redact("Authorization: Bearer sk-abcdefghijklmnop")
    assert emb.redact("plain message") == "plain message"


# ---------------------------------------------------------------------------
# Surfacing the provider's own reason
#
# Google answers an invalid key with HTTP 400 and puts the reason only in the
# body, so "HTTP Error 400: Bad Request" told the user nothing.
# ---------------------------------------------------------------------------

GEMINI_BAD_KEY_BODY = json.dumps({
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
    }
}).encode("utf-8")


def _http_error_with_body(code, body):
    error = emb.urllib.error.HTTPError(
        url="https://example.invalid", code=code, msg="Bad Request", hdrs={}, fp=None
    )
    error.read = lambda: body
    return error


def test_error_detail_extracts_the_api_message():
    detail = emb.error_detail(_http_error_with_body(400, GEMINI_BAD_KEY_BODY))

    assert "400" in detail
    assert "API key not valid" in detail
    assert "INVALID_ARGUMENT" in detail


OPENAI_BAD_KEY_BODY = json.dumps({
    "error": {
        "message": "Incorrect API key provided: sk-***. You can find your API key at ...",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
}).encode("utf-8")


def test_error_detail_handles_the_openai_shape():
    """OpenAI uses type/code where Google uses status."""
    detail = emb.error_detail(_http_error_with_body(401, OPENAI_BAD_KEY_BODY))

    assert "Incorrect API key provided" in detail
    assert "invalid_api_key" in detail


def test_an_openai_rejection_names_the_right_variable(monkeypatch):
    def bad_key(request, timeout=None):
        raise _http_error_with_body(401, OPENAI_BAD_KEY_BODY)

    monkeypatch.setenv("TACIT_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(emb.urllib.request, "urlopen", bad_key)
    monkeypatch.setattr(EmbeddingService, "_respect_request_interval", lambda self: None)

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        EmbeddingService.get().embed_documents(["x"])

    message = str(excinfo.value)
    assert "Incorrect API key" in message
    assert "OPENAI_API_KEY" in message
    assert "GEMINI_API_KEY" not in message


def test_body_message_survives_unexpected_shapes():
    assert emb.body_message('{"detail": "not found"}') == "not found"
    assert emb.body_message('{"message": "plain"}') == "plain"
    assert emb.body_message('{"error": "a bare string"}') == "a bare string"
    assert emb.body_message("not json at all") == "not json at all"
    assert emb.body_message("") == ""


def test_quota_errors_get_a_pacing_hint_not_an_auth_hint():
    detail = "HTTP 429 Too Many Requests: [RESOURCE_EXHAUSTED] Quota exceeded"

    hint = emb.remediation_hint("Gemini", detail)

    assert "allowance limit" in hint
    assert "TACIT_EMBED_MIN_INTERVAL" in hint
    assert "GEMINI_API_KEY" not in hint, "a quota problem is not a credential problem"


def test_unknown_errors_get_no_misleading_hint():
    assert emb.remediation_hint("Gemini", "HTTP 500 Internal Server Error") == ""


def test_error_detail_falls_back_to_a_raw_body():
    detail = emb.error_detail(_http_error_with_body(500, b"<html>gateway blew up</html>"))

    assert "gateway blew up" in detail


def test_error_detail_handles_a_non_http_exception():
    assert "connection reset" in emb.error_detail(OSError("connection reset"))


def test_a_rejected_key_reports_the_reason_and_a_hint(monkeypatch):
    """The exact reported failure: HTTP 400 with the cause hidden in the body."""

    def bad_key(request, timeout=None):
        raise _http_error_with_body(400, GEMINI_BAD_KEY_BODY)

    service, _ = _gemini_service(monkeypatch, bad_key, pace=False)

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        service.embed_documents(["x"])

    message = str(excinfo.value)
    assert "API key not valid" in message
    assert "GEMINI_API_KEY" in message, "the hint must name the variable to check"


def test_a_bad_request_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def bad_request(request, timeout=None):
        calls["n"] += 1
        raise _http_error_with_body(400, GEMINI_BAD_KEY_BODY)

    service, slept = _gemini_service(monkeypatch, bad_request, pace=False)

    with pytest.raises(EmbeddingUnavailable):
        service.embed_documents(["x"])

    assert calls["n"] == 1
    assert slept == []


def test_key_hint_masks_the_credential(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ")

    hint = EmbeddingService.get().key_hint()

    assert hint.startswith("AIzaSy")
    assert hint.endswith("WXYZ")
    assert "GHIJKLMNOPQRST" not in hint


def test_key_hint_without_a_key():
    assert EmbeddingService.get().key_hint() == "none"
