"""Tests for `tacit get` prefix resolution and the `grep` CLI + memory_grep tool.

`grep` is deliberately a literal substring search over titles and summaries: it
must not read content, must not tokenise, and must not need an embedding model.
"""

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers


@pytest.fixture(scope="module")
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_grep_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="module")
def storage(tmp_dir):
    """One database for the module; each test empties it, so construction is paid once."""
    return MemoryStorage(tmp_dir / ".tacit" / "memory.db")


@pytest.fixture(autouse=True)
def fast_writes(monkeypatch):
    """The corpus is rebuilt per test, so keep each write cheap.

    Markdown dual-write and the embedding attempt dominate `add_memory`; neither
    is what these read-path tests are exercising.
    """
    from src.search.embeddings import EmbeddingService
    from src.utils.config import Config

    monkeypatch.setattr(Config, "DUAL_WRITE", False, raising=False)
    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))


@pytest.fixture(autouse=True)
def corpus(storage, fast_writes):
    """Three memories per test, with genuinely distinct UUID prefixes.

    Emptied per test rather than rebuilt: constructing a ``MemoryStorage`` runs
    the full schema bootstrap, which is the slow part.
    """
    storage.clear_all_memories()
    now = datetime.now(timezone.utc).timestamp()
    nodes = {
        "title_hit": MemoryNode(
            id=str(uuid.uuid4()),
            title="Cloud SQL PostgreSQL 18 + pgvector init",
            summary="Initialised the database with the vector extension",
            content="Body text containing zanzibar, which grep must not search.",
            type="architecture", tags=["db"], timestamp=now,
        ),
        "summary_hit": MemoryNode(
            id=str(uuid.uuid4()),
            title="Reverse-engineered PMTV Extra",
            summary="R2 storage plus AES-128 HLS packaging for pgvector pipelines",
            content="Body only.", type="decision", tags=["video"], timestamp=now - 60,
        ),
        "body_only": MemoryNode(
            id=str(uuid.uuid4()),
            title="Unrelated memory",
            summary="Nothing to see here",
            content="pgvector appears in this body only, and zanzibar too.",
            type="context", tags=["misc"], timestamp=now - 120,
        ),
    }
    for node in nodes.values():
        storage.add_memory(node)
    return nodes


# ---------------------------------------------------------------------------
# grep semantics
# ---------------------------------------------------------------------------

def test_grep_finds_title_matches(storage, corpus):
    assert [n.id for n in storage.grep_memories("Cloud SQL")] == [corpus["title_hit"].id]


def test_grep_finds_summary_matches(storage, corpus):
    assert [n.id for n in storage.grep_memories("AES-128")] == [corpus["summary_hit"].id]


def test_grep_never_reads_content(storage, corpus):
    """Searching bodies would just make it a worse `search`."""
    assert storage.grep_memories("zanzibar") == []

    hits = {n.id for n in storage.grep_memories("pgvector")}
    assert hits == {corpus["title_hit"].id, corpus["summary_hit"].id}
    assert corpus["body_only"].id not in hits


def test_grep_is_case_insensitive(storage, corpus):
    assert [n.id for n in storage.grep_memories("cLoUd sQl")] == [corpus["title_hit"].id]


def test_grep_matches_partial_words(storage, corpus):
    assert len(storage.grep_memories("pgvec")) == 2


def test_grep_treats_like_wildcards_literally(storage):
    """A keyword of '%' must not turn into 'match everything'."""
    assert storage.grep_memories("%") == []
    assert storage.grep_memories("_") == []


def test_grep_ranks_title_hits_above_summary_hits(storage, corpus):
    assert storage.grep_memories("pgvector")[0].id == corpus["title_hit"].id


def test_grep_filters_by_type(storage, corpus):
    assert [n.id for n in storage.grep_memories("pgvector", memory_type="decision")] == [
        corpus["summary_hit"].id
    ]


def test_grep_excludes_superseded_by_default(storage, corpus):
    storage.supersede_memory(
        target_id=corpus["title_hit"].id, by_id=corpus["summary_hit"].id, reason="replaced"
    )

    assert [n.id for n in storage.grep_memories("pgvector")] == [corpus["summary_hit"].id]
    assert len(storage.grep_memories("pgvector", include_superseded=True)) == 2


def test_grep_with_blank_keyword_returns_nothing(storage):
    assert storage.grep_memories("") == []
    assert storage.grep_memories("   ") == []


# ---------------------------------------------------------------------------
# `get` is an exact lookup
# ---------------------------------------------------------------------------

def test_cli_get_requires_the_full_uuid(tmp_dir, corpus):
    """A prefix must not resolve: get retrieves one specific node's content."""
    target = corpus["title_hit"]

    result = CliRunner().invoke(app, ["get", target.id[:8], "--project", str(tmp_dir)])

    assert result.exit_code == 1
    flat = " ".join(result.stdout.split())
    assert "exact UUID" in flat
    assert "tacit grep" in flat, "point at how to find the real id"


def test_cli_get_prints_the_content_verbatim(tmp_dir, storage):
    """Rich markup parsing used to delete any [lowercase...] span from content."""
    body = (
        "pip fails with `[WinError 32]` while the launcher is in use.\n"
        "See [the docs](https://example.com/docs) and [bold]not-a-style[/bold].\n"
        "- item [one]\n"
        "- item [two]\n"
    )
    node = MemoryNode(
        id=str(uuid.uuid4()), title="Fidelity probe", summary="brackets",
        content=body, type="error",
    )
    storage.add_memory(node)

    result = CliRunner().invoke(app, ["get", node.id, "--project", str(tmp_dir)])

    assert result.exit_code == 0
    for fragment in (
        "[WinError 32]",
        "[the docs](https://example.com/docs)",
        "[bold]not-a-style[/bold]",
        "[one]",
        "[two]",
    ):
        assert fragment in result.stdout, f"{fragment} was dropped from the content"


def test_cli_get_raw_emits_plain_markdown(tmp_dir, storage):
    node = MemoryNode(
        id=str(uuid.uuid4()), title="Raw probe", summary="s",
        content="Body with [the docs](https://example.com) inside.", type="context",
    )
    storage.add_memory(node)

    result = CliRunner().invoke(app, ["get", node.id, "--raw", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert "[the docs](https://example.com)" in result.stdout
    assert "Memory Node:" not in result.stdout, "no panel when --raw is used"


def test_cli_get_reports_a_missing_id(tmp_dir):
    result = CliRunner().invoke(
        app, ["get", "11111111-2222-4333-8444-000000000000", "--project", str(tmp_dir)]
    )

    assert result.exit_code == 1
    assert "No memory node with the exact UUID" in " ".join(result.stdout.split())


def test_cli_get_suggests_the_right_id_when_the_leading_character_is_dropped(tmp_dir, corpus):
    """The exact reported slip: 548bfe4f… was pasted as 48bfe4f…."""
    target = corpus["title_hit"]
    truncated = target.id[1:]

    result = CliRunner().invoke(app, ["get", truncated, "--project", str(tmp_dir)])

    assert result.exit_code == 1, "get must still refuse an inexact id"
    flat = " ".join(result.stdout.split())
    assert "Did you mean" in flat
    assert target.id in flat, "the near-miss candidate must be shown in full"


def test_cli_get_suggests_for_a_missing_trailing_character(tmp_dir, corpus):
    target = corpus["summary_hit"]

    result = CliRunner().invoke(app, ["get", target.id[:-1], "--project", str(tmp_dir)])

    assert result.exit_code == 1
    assert target.id in " ".join(result.stdout.split())


def test_cli_get_stays_silent_when_nothing_is_close(tmp_dir):
    result = CliRunner().invoke(
        app, ["get", "99999999-9999-4999-8999-999999999999", "--project", str(tmp_dir)]
    )

    assert result.exit_code == 1
    assert "Did you mean" not in result.stdout


def test_find_id_candidates_ignores_tiny_fragments(storage):
    assert storage.find_id_candidates("ab") == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_search_prints_a_uuid_that_get_accepts(tmp_dir, corpus):
    """The reported trap: `search` printed `a1c877e7`, then `get` rejected it.

    A UUID inside a table is not safe -- Rich shrinks columns to fit the
    terminal and truncates it -- so ids are listed separately.
    """
    target = corpus["title_hit"]

    result = CliRunner().invoke(app, ["search", "pgvector", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert target.id in result.stdout, "the full UUID must be printed, not a prefix"

    fetched = CliRunner().invoke(app, ["get", target.id, "--project", str(tmp_dir)])
    assert fetched.exit_code == 0, "the id printed by search must be usable by get"


def test_cli_grep_prints_a_uuid_that_get_accepts(tmp_dir, corpus):
    target = corpus["summary_hit"]

    result = CliRunner().invoke(app, ["grep", "AES-128", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert target.id in result.stdout

    fetched = CliRunner().invoke(app, ["get", target.id, "--project", str(tmp_dir)])
    assert fetched.exit_code == 0


def test_cli_recent_prints_a_uuid_that_get_accepts(tmp_dir, corpus):
    target = corpus["title_hit"]

    result = CliRunner().invoke(app, ["recent", "--days", "1", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert target.id in result.stdout

    fetched = CliRunner().invoke(app, ["get", target.id, "--project", str(tmp_dir)])
    assert fetched.exit_code == 0


def test_ids_survive_a_narrow_terminal(tmp_dir, corpus, monkeypatch):
    """A 40-column terminal must still yield a complete, usable UUID."""
    from src.cli import main as cli_main

    monkeypatch.setattr(cli_main.console, "_width", 40, raising=False)
    target = corpus["title_hit"]

    result = CliRunner().invoke(app, ["grep", "pgvector", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert target.id in result.stdout, "the UUID must not be truncated to fit"


def test_cli_grep_prints_a_table(tmp_dir, corpus):
    result = CliRunner().invoke(app, ["grep", "pgvector", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    flat = " ".join(result.stdout.split())
    assert "Cloud SQL" in flat
    assert "[architecture]" in flat, "the category must survive Rich markup parsing"


def test_cli_grep_says_where_to_look_when_nothing_matches(tmp_dir):
    result = CliRunner().invoke(app, ["grep", "nonexistentxyz", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    flat = " ".join(result.stdout.split())
    assert "No memory title or summary contains" in flat
    assert "tacit search" in flat, "point at search for content and meaning"


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------

def test_memory_grep_handler_reports_the_match_location(storage, tmp_dir, corpus):
    handlers = MemoryMCPHandlers(default_storage=storage, project_root=tmp_dir)

    res = handlers.handle_memory_grep("AES-128")

    assert res["count"] == 1
    assert res["results"][0]["matched_in"] == "summary"
    assert "summary match" in res["formatted"]


def test_memory_grep_handler_explains_an_empty_result(storage, tmp_dir):
    handlers = MemoryMCPHandlers(default_storage=storage, project_root=tmp_dir)

    res = handlers.handle_memory_grep("nonexistentxyz")

    assert res["count"] == 0
    assert "memory_search" in res["formatted"]


def test_memory_get_requires_the_full_uuid(storage, tmp_dir, corpus):
    """Exact match only: a partial id must not resolve to a guessed node."""
    target = corpus["title_hit"]
    handlers = MemoryMCPHandlers(default_storage=storage, project_root=tmp_dir)

    res = handlers.handle_memory_get(target.id[:8])

    assert res["found"] is False
    assert "exact UUID" in res["message"]
    assert "memory_grep" in res["message"], "point at how to find the real id"
    assert target.id in res["message"], "the near-miss candidate must be offered"
    assert "Did you mean" in res["message"]


def test_ids_are_listed_one_per_line_even_with_newlines_in_a_title(tmp_dir, storage):
    """Auto-generated titles from older versions contain the body's newlines."""
    node = MemoryNode(
        id=str(uuid.uuid4()),
        title="Architecture: ### 1. Context\nLarge multi-gigabyte files",
        summary="s", content="c",
    )
    storage.add_memory(node)

    result = CliRunner().invoke(app, ["grep", "Architecture", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    line = next(l for l in result.stdout.splitlines() if node.id in l)
    assert "\n" not in line
    assert "###" in line or "Context" in line, "the label is flattened, not dropped"


def test_memory_get_returns_the_full_content(storage, tmp_dir, corpus):
    target = corpus["title_hit"]
    handlers = MemoryMCPHandlers(default_storage=storage, project_root=tmp_dir)

    res = handlers.handle_memory_get(target.id)

    assert res["found"] is True
    assert res["memory"]["title"] == "Cloud SQL PostgreSQL 18 + pgvector init"
    assert "zanzibar" in res["memory"]["content"], "the stored body must come back intact"


def test_memory_grep_schema_matches_the_implementation(storage, tmp_dir, corpus):
    """The published schema and the handler must not drift apart."""
    from src.mcp.tools import TOOL_DEFINITIONS

    definition = next(t for t in TOOL_DEFINITIONS if t["name"] == "memory_grep")

    assert definition["inputSchema"]["required"] == ["keyword"]
    assert set(definition["inputSchema"]["properties"]) == {
        "keyword", "type", "limit", "include_superseded"
    }

    handlers = MemoryMCPHandlers(default_storage=storage, project_root=tmp_dir)
    res = handlers.handle_memory_grep(keyword="pgvector", type="decision")
    assert res["count"] == 1
