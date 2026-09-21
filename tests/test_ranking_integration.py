"""End-to-end ranking tests: PageRank authority driving briefing and search.

These use a real ``MemoryStorage`` so the graph is built through the same
``add_memory`` path production uses (which is what writes the ``edges`` rows).
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.bootstrap import BootstrapEngine
from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.search.embeddings import EmbeddingService


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    """Ranking must be provable without an embedding backend or a model download."""
    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))
    EmbeddingService.reset()
    yield
    EmbeddingService.reset()


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_ranking_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def storage(tmp_dir):
    return MemoryStorage(tmp_dir / ".tacit" / "memory.db")


def _node(node_id, days_ago=0, **kwargs):
    return MemoryNode(
        id=node_id,
        timestamp=(datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp(),
        content=kwargs.pop("content", f"Content for {node_id}"),
        title=kwargs.pop("title", f"Title for {node_id}"),
        summary=kwargs.pop("summary", f"Summary for {node_id}"),
        tags=kwargs.pop("tags", [node_id]),
        **kwargs,
    )


def _build_foundation_graph(storage):
    """One old foundation plus three recent memories built on it, and a recent leaf."""
    storage.add_memory(_node("foundation", days_ago=200, impact="medium"))
    for index in range(3):
        storage.add_memory(_node(f"child{index}", days_ago=1, parents=["foundation"]))
    storage.add_memory(_node("leaf", days_ago=0, impact="high"))


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

def test_briefing_promotes_the_foundation_over_fresher_leaf(storage):
    """The whole point of authority: what others were built on beats what is new."""
    _build_foundation_graph(storage)

    briefing = BootstrapEngine.generate_briefing(storage, budget=4000)

    ids = [node["id"] for node in briefing["full"]] + [
        node["id"] for nodes in briefing["brief"].values() for node in nodes
    ]
    assert ids[0] == "foundation"
    assert "leaf" in ids
    assert ids.index("foundation") < ids.index("leaf")


def test_briefing_timeframe_filters_results_without_changing_ranking(storage):
    """Timeframe selects what may appear; authority is still computed globally."""
    storage.add_memory(_node("old_foundation", days_ago=365, impact="high"))
    storage.add_memory(_node("recent_leaf", days_ago=1, impact="high", parents=["old_foundation"]))

    everything = BootstrapEngine.generate_briefing(storage, budget=4000)
    assert {n["id"] for n in everything["full"]} == {"old_foundation", "recent_leaf"}

    this_week = BootstrapEngine.generate_briefing(storage, budget=4000, timeframe="week")
    visible = {n["id"] for n in this_week["full"]}
    visible |= {n["id"] for nodes in this_week["brief"].values() for n in nodes}

    assert visible == {"recent_leaf"}, "the year-old foundation is outside the window"


def test_empty_timeframe_window_reports_clearly(storage):
    storage.add_memory(_node("ancient", days_ago=800))

    result = BootstrapEngine.generate_briefing(storage, timeframe="week")

    assert result["count"] == 0
    assert "timeframe" in result["formatted"].lower()


def test_invalid_timeframe_does_not_break_bootstrapping(storage):
    storage.add_memory(_node("anything", days_ago=1))

    result = BootstrapEngine.generate_briefing(storage, timeframe="banana")

    assert result["count"] == 1


def test_scope_hint_boosts_matching_memories(storage):
    """scope_hint is advertised by the MCP schema, so it must actually do something."""
    storage.add_memory(_node("auth_note", days_ago=1, scope=["src/auth/session.py"]))
    storage.add_memory(_node("ui_note", days_ago=1, scope=["src/ui/button.tsx"]))

    biased = BootstrapEngine.generate_briefing(
        storage, budget=4000, scope_hint=["src/auth"]
    )

    ids = [n["id"] for n in biased["full"]] + [
        n["id"] for nodes in biased["brief"].values() for n in nodes
    ]
    assert ids[0] == "auth_note"


def test_superseded_memories_stay_out_of_the_briefing(storage):
    _build_foundation_graph(storage)
    storage.add_memory(_node("mistake", days_ago=1, impact="high"))
    storage.supersede_memory(target_id="mistake", by_id="leaf", reason="wrong")

    briefing = BootstrapEngine.generate_briefing(storage, budget=4000)

    assert "mistake" not in briefing["formatted"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_authority_breaks_a_relevance_tie(storage):
    """Two equally relevant memories: the one others were built on wins."""
    shared = dict(
        content="Connection pool exhaustion under concurrent writes",
        title="Connection pool exhaustion",
        summary="Pool of 10 was too small for concurrent writers",
        tags=["database", "pool"],
    )
    storage.add_memory(MemoryNode(id="ignored", timestamp=datetime.now(timezone.utc).timestamp(), **shared))
    storage.add_memory(
        MemoryNode(id="foundation", timestamp=datetime.now(timezone.utc).timestamp(), **shared)
    )
    storage.add_memory(_node("dependent", days_ago=0, parents=["foundation"]))

    results = storage.search_hybrid(query="connection pool exhaustion", limit=5, mode="keyword")

    ranked = [item["node"].id for item in results]
    assert ranked[0] == "foundation"
    assert "ignored" in ranked, "the lower-authority twin is still returned"


def test_search_still_returns_results_when_there_are_no_links(storage):
    """An unlinked project must fall back to pure relevance, not break."""
    storage.add_memory(
        _node("solo", days_ago=0, content="WAL mode fixes SQLite locking", title="SQLite WAL mode")
    )

    results = storage.search_hybrid(query="SQLite WAL mode", limit=5, mode="keyword")

    assert [item["node"].id for item in results] == ["solo"]


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------

def test_search_cli_shows_category_and_preserves_bracketed_titles(storage, tmp_dir):
    """Regression: Rich parsed `[error]` and `[WinError 32]` as style tags and
    silently deleted them, leaving a blank Type column."""
    from typer.testing import CliRunner

    from src.cli.main import app

    storage.add_memory(
        _node("winerr", days_ago=0, title="[WinError 32] blocks pip from replacing tacit.exe",
              content="Windows locks the running console script during pip install.",
              type="error", tags=["windows", "pip"])
    )

    result = CliRunner().invoke(app, ["search", "WinError", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert "[error]" in result.stdout, "the category must survive Rich markup parsing"
    assert "[WinError 32]" in result.stdout
