"""An empty search must hand the agent a way to find the memory, not a shrug.

Hybrid search can miss a real memory because the wording differs, the node is
superseded, or its content was never embedded. The MCP result therefore carries
an executable five-sub-agent sweep over the whole store, in 20% chunks backed by
``memory_chronicle(limit=..., offset=...)``.
"""

import math
import uuid

import pytest

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers
from src.search.embeddings import EmbeddingService
from src.utils.config import Config


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    from src.utils.config import Config as Cfg

    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))
    monkeypatch.setattr(EmbeddingService, "provider", property(lambda self: "none"))
    monkeypatch.setattr(Cfg, "DUAL_WRITE", False, raising=False)
    EmbeddingService.reset()
    yield
    EmbeddingService.reset()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "shop"
    (root / ".git").mkdir(parents=True)
    (root / "backend").mkdir()
    return root


def _add(project, title, number=0):
    storage = MemoryStorage(Config.get_db_path(project))
    node = MemoryNode(
        id=str(uuid.uuid4()),
        title=title,
        summary=f"{title} summary",
        content=f"{title} full content body {number}",
        type="decision",
        tags=["t"],
        scope=["backend"],
        impact="medium",
    )
    storage.add_memory(node)
    return node


def test_empty_search_returns_the_five_chunk_protocol(project):
    _add(project, "Async DB sessions")
    handlers = MemoryMCPHandlers(project_root=project)

    res = handlers.handle_memory_search(query="quantum flux capacitor")

    assert res["count"] == 0
    assert res["total_memories"] == 1
    assert res["fallback"]["strategy"] == "exhaustive_chunked_scan"
    assert res["fallback"]["chunk_size"] == 1
    assert res["fallback"]["agents"] == 1
    assert res["fallback"]["chunks"] == [{"agent": 1, "offset": 0, "limit": 1}]

    text = res["formatted"]
    assert "TACIT EXHAUSTIVE FALLBACK" in text
    assert "memory_chronicle(limit=1, offset=0" in text
    assert "brief=false" in text
    assert "include_superseded=true" in text
    assert "include_retracted=true" in text
    assert str(project) in text
    assert "GEMINI_API_KEY is not set" in text


def test_large_store_is_split_into_five_twenty_percent_chunks(project):
    for index in range(23):
        _add(project, f"Memory {index}", index)
    handlers = MemoryMCPHandlers(project_root=project)

    res = handlers.handle_memory_search(query="nothing matches this at all")

    expected_chunk = math.ceil(23 / 5)
    assert expected_chunk == 5
    assert res["fallback"]["agents"] == 5
    assert res["fallback"]["chunk_size"] == expected_chunk
    assert [c["offset"] for c in res["fallback"]["chunks"]] == [0, 5, 10, 15, 20]
    assert [c["limit"] for c in res["fallback"]["chunks"]] == [5, 5, 5, 5, 3]
    # Every chunk call appears in the text the agent actually receives.
    for chunk in res["fallback"]["chunks"]:
        assert (
            f"memory_chronicle(limit={chunk['limit']}, offset={chunk['offset']}"
            in res["formatted"]
        )


def test_scoped_empty_search_says_to_retry_without_scope(project):
    _add(project, "Backend decision")
    handlers = MemoryMCPHandlers(project_root=project)

    res = handlers.handle_memory_search(
        query="quantum flux capacitor", scope_hint=["backend"]
    )

    assert "retry once without scope_hint" in res["formatted"]


def test_an_empty_store_says_there_is_nothing_to_scan(project):
    handlers = MemoryMCPHandlers(project_root=project)

    res = handlers.handle_memory_search(query="anything")

    assert res["total_memories"] == 0
    assert res["fallback"]["strategy"] == "none"
    assert "store is empty" in res["formatted"]
    assert "TACIT EXHAUSTIVE FALLBACK" not in res["formatted"]


def test_chunking_covers_every_memory(project):
    """The five chunks must partition the store, with no gap or overlap."""
    for index in range(23):
        _add(project, f"Memory {index}", index)
    handlers = MemoryMCPHandlers(project_root=project)

    res = handlers.handle_memory_search(query="no match")
    chunks = res["fallback"]["chunks"]

    covered = []
    for chunk in chunks:
        page = handlers.handle_memory_chronicle(
            limit=chunk["limit"], offset=chunk["offset"]
        )
        covered.extend(entry["id"] for entry in page["entries"])

    assert len(covered) == 23
    assert len(set(covered)) == 23
