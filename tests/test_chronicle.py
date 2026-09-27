"""The chronicle: every memory, oldest first, for whole-history analysis.

`memory_context` is selective by design — ranked, budgeted, deduplicated. The
chronicle is the opposite, and the difference matters: an agent asked "why is it
built this way" needs the decisions that were later replaced, in the order they
happened.
"""

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core.chronicle import ChronicleEngine
from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_chronicle_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def project(tmp_dir):
    root = tmp_dir / "shop"
    (root / "backend").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


@pytest.fixture
def storage(project):
    return MemoryStorage(project / ".tacit" / "memory.db")


@pytest.fixture(autouse=True)
def fast_writes(monkeypatch):
    from src.search.embeddings import EmbeddingService
    from src.utils.config import Config

    monkeypatch.setattr(Config, "DUAL_WRITE", False, raising=False)
    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))


def _add(storage, title, scope, days_ago, type="decision", status="active"):
    node = MemoryNode(
        id=str(uuid.uuid4()),
        title=title,
        summary=f"{title} summary",
        content=f"{title} full content body",
        type=type,
        tags=["t"],
        scope=scope,
        impact="medium",
        status=status,
        timestamp=(datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp(),
    )
    assert storage.add_memory(node) is True
    return node


def test_history_is_oldest_first(storage):
    _add(storage, "Newest decision", ["backend"], days_ago=1)
    _add(storage, "Oldest decision", ["backend"], days_ago=90)
    _add(storage, "Middle decision", ["backend"], days_ago=30)

    res = ChronicleEngine.build(storage)

    titles = [entry["title"] for entry in res["entries"]]
    assert titles == ["Oldest decision", "Middle decision", "Newest decision"]
    assert res["entries"][0]["index"] == 1


def test_superseded_memories_are_included_by_default(storage):
    """A replaced decision is part of the reasoning history."""
    _add(storage, "Old approach", ["backend"], days_ago=60, status="superseded")
    _add(storage, "New approach", ["backend"], days_ago=5)

    default = ChronicleEngine.build(storage)
    active_only = ChronicleEngine.build(storage, include_superseded=False)

    assert default["count"] == 2
    assert "[SUPERSEDED]" in default["formatted"]
    assert active_only["count"] == 1


def test_retracted_memories_are_excluded_unless_asked_for(storage):
    _add(storage, "Mistaken approach", ["backend"], days_ago=10, status="retracted")
    _add(storage, "Sound approach", ["backend"], days_ago=5)

    assert ChronicleEngine.build(storage)["count"] == 1
    with_retracted = ChronicleEngine.build(storage, include_retracted=True)
    assert with_retracted["count"] == 2
    assert "[RETRACTED]" in with_retracted["formatted"]


def test_the_scope_filter_applies_to_history_too(storage):
    _add(storage, "Backend decision", ["backend/app"], days_ago=20)
    _add(storage, "Frontend decision", ["frontend/src"], days_ago=10)

    res = ChronicleEngine.build(storage, scope_hint=["backend/app"])

    assert [entry["title"] for entry in res["entries"]] == ["Backend decision"]
    assert "(scope filter: backend/app)" in res["formatted"]


def test_type_and_timeframe_narrow_the_timeline(storage):
    _add(storage, "An error", ["backend"], days_ago=3, type="error")
    _add(storage, "A decision", ["backend"], days_ago=3, type="decision")
    _add(storage, "Ancient decision", ["backend"], days_ago=400, type="decision")

    by_type = ChronicleEngine.build(storage, memory_type="error")
    assert [entry["title"] for entry in by_type["entries"]] == ["An error"]

    by_window = ChronicleEngine.build(storage, timeframe="30d")
    assert "Ancient decision" not in [entry["title"] for entry in by_window["entries"]]


def test_limit_reports_truncation_honestly(storage):
    for index in range(5):
        _add(storage, f"Memory {index}", ["backend"], days_ago=100 - index * 10)

    res = ChronicleEngine.build(storage, limit=2)

    assert res["count"] == 2
    assert res["truncated"] is True
    assert "timeline truncated" in res["formatted"]


def test_limit_zero_returns_everything(storage):
    for index in range(12):
        _add(storage, f"Memory {index}", ["backend"], days_ago=100 - index)

    res = ChronicleEngine.build(storage, limit=0)

    assert res["count"] == 12
    assert res["truncated"] is False


def test_full_entries_carry_content_and_lineage(storage):
    parent = _add(storage, "Foundational decision", ["backend"], days_ago=50)
    child = MemoryNode(
        id=str(uuid.uuid4()),
        title="Follow-up decision",
        summary="Built on the foundation",
        content="Body",
        type="decision",
        tags=["t"],
        scope=["backend"],
        impact="high",
        timestamp=datetime.now(timezone.utc).timestamp(),
        parents=[parent.id],
    )
    storage.add_memory(child)

    res = ChronicleEngine.build(storage)

    assert "Foundational decision full content body" in res["formatted"]
    assert f"derives from: `{parent.id}`" in res["formatted"]
    # The complete UUID, so the timeline is directly actionable.
    assert f"`{child.id}`" in res["formatted"]


def test_long_content_is_elided(storage):
    node = MemoryNode(
        id=str(uuid.uuid4()),
        title="Huge decision",
        summary="Long one",
        content="x" * 5000,
        type="decision",
        tags=["t"],
        scope=["backend"],
        timestamp=datetime.now(timezone.utc).timestamp(),
    )
    storage.add_memory(node)

    res = ChronicleEngine.build(storage, content_chars=100)

    assert "chars elided" in res["formatted"]
    assert len(res["formatted"]) < 2000


def test_brief_mode_is_one_line_per_memory(storage):
    _add(storage, "First", ["backend"], days_ago=10)
    _add(storage, "Second", ["backend"], days_ago=1)

    res = ChronicleEngine.build(storage, brief=True)

    assert res["formatted"].count("[00") == 2
    assert "full content body" not in res["formatted"]


def test_empty_history_says_so(storage):
    res = ChronicleEngine.build(storage)

    assert res["count"] == 0
    assert "no institutional history yet" in res["formatted"]


def test_entries_are_grouped_by_month(storage):
    _add(storage, "Old", ["backend"], days_ago=200)
    _add(storage, "Recent", ["backend"], days_ago=1)

    res = ChronicleEngine.build(storage)

    assert res["formatted"].count("── ") >= 2


# ---------------------------------------------------------------------------
# CLI and MCP surfaces
# ---------------------------------------------------------------------------

def test_cli_chronicle_prints_the_timeline(project):
    result = CliRunner().invoke(app, ["chronicle", "--project", str(project)])

    assert result.exit_code == 0
    assert "TACIT CHRONICLE" in result.stdout


def test_cli_chronicle_json(project):
    import json

    CliRunner().invoke(
        app, ["remember", "A decision worth keeping", "--title", "Kept decision",
              "--scope", "backend", "--project", str(project)]
    )

    result = CliRunner().invoke(app, ["chronicle", "--json", "--project", str(project)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] >= 1
    assert payload["entries"][0]["title"]


def test_mcp_chronicle_returns_the_same_timeline(project):
    handlers = MemoryMCPHandlers(project_root=project)
    handlers.handle_memory_add(
        content="Body",
        title="MCP recorded decision",
        summary="Recorded through the tool",
        scope=["backend"],
    )

    res = handlers.handle_memory_chronicle()

    assert res["count"] == 1
    assert "MCP recorded decision" in res["formatted"]


def test_mcp_chronicle_reports_an_unresolved_workspace(tmp_dir):
    handlers = MemoryMCPHandlers(project_root=tmp_dir, unresolved_reason="no workspace")

    res = handlers.handle_memory_chronicle()

    assert res["count"] == 0
    assert "no workspace" in res["message"]
