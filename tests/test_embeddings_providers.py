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

    def boom(request, timeout=None):
        raise OSError("connection reset")

    monkeypatch.setattr(emb.urllib.request, "urlopen", boom)

    with pytest.raises(EmbeddingUnavailable) as excinfo:
        EmbeddingService.get().embed_documents(["x"])

    assert "OpenAI" in str(excinfo.value)


def test_openai_truncated_response_is_rejected(monkeypatch, no_local_model):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        emb.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"data": [{"index": 0, "embedding": [0.1]}]}),
    )

    with pytest.raises(EmbeddingUnavailable):
        EmbeddingService.get().embed_documents(["one", "two"])


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
