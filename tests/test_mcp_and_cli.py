"""Unit tests for MCP Handlers and CLI interface commands."""

import tempfile
from pathlib import Path
import pytest
from typer.testing import CliRunner

from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers
from src.mcp.server import create_mcp_server
from src.cli.main import app
from src.utils.config import Config


@pytest.fixture
def mcp_fixture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "mcp_test.db"
        storage = MemoryStorage(db_path)
        handlers = MemoryMCPHandlers(storage)
        yield storage, handlers


def test_mcp_add_and_search(mcp_fixture):
    storage, handlers = mcp_fixture

    # Test memory_add handler
    add_res = handlers.handle_memory_add(
        content="Configured Redis cache with 3600s TTL for session tokens.",
        type="decision",
        title="Redis TTL Decision",
        tags=["redis", "cache"],
        impact="high",
    )
    assert add_res["success"] is True
    node_id = add_res["id"]

    # Test memory_get handler
    get_res = handlers.handle_memory_get(node_id)
    assert get_res["found"] is True
    assert "Redis TTL Decision" in get_res["formatted"]

    # Test memory_search handler
    search_res = handlers.handle_memory_search("Redis")
    assert search_res["count"] == 1
    assert search_res["results"][0]["id"] == node_id

    # Test memory_recent handler
    recent_res = handlers.handle_memory_recent(days=1)
    assert recent_res["count"] == 1

    # Test memory_context handler
    context_res = handlers.handle_memory_context("week")
    assert context_res["count"] == 1
    assert "DECISION" in context_res["formatted"] or "Core context" in context_res["formatted"]


def test_mcp_add_batch(mcp_fixture):
    storage, handlers = mcp_fixture

    entries = [
        {
            "content": "Database pool exhaustion under high concurrent load with error: OperationalError('too many connections')",
            "type": "error",
            "title": "Postgres Pool Exhaustion",
            "tags": ["postgres", "error", "pool"],
            "impact": "high",
        },
        {
            "content": "Increased database pool max overflow to 50 and tuned recycle time to 1800s to resolve connection exhaustion.",
            "type": "decision",
            "title": "Tuned Postgres Pool Capacity",
            "tags": ["postgres", "decision", "pool"],
            "impact": "high",
            "parents": ["$prev"],
        },
    ]

    batch_res = handlers.handle_memory_add_batch(entries)
    assert batch_res["success"] is True
    assert batch_res["count"] == 2
    assert len(batch_res["results"]) == 2

    error_id = batch_res["results"][0]["id"]
    decision_id = batch_res["results"][1]["id"]

    # Verify that the second node's parent is the first node's ID
    node_decision = storage.get_memory(decision_id)
    assert node_decision is not None
    assert error_id in node_decision.parents


def test_cli_commands():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "cli_memories"
        Config.MEMORY_DIR = test_dir
        Config.DB_PATH = test_dir / "memory.db"

        # 1. Test init
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output

        # 2. Test remember
        result = runner.invoke(app, [
            "remember",
            "Switched to async database sessions for performance",
            "--type", "decision",
            "--title", "Async DB Sessions",
            "--tags", "db,async",
            "--impact", "high"
        ])
        assert result.exit_code == 0
        assert "Recorded" in result.output

        # 3. Test search
        result = runner.invoke(app, ["search", "sessions"])
        assert result.exit_code == 0
        assert "Sessi" in result.output or "DECISION" in result.output

        # 4. Test recent
        result = runner.invoke(app, ["recent", "--days", "1"])
        assert result.exit_code == 0

        # 5. Test export
        export_out = test_dir / "export"
        result = runner.invoke(app, ["export", "--output", str(export_out)])
        assert result.exit_code == 0
        assert "Export Complete" in result.output
        assert (export_out / "INDEX.md").exists()

        # 6. Test projects command
        result = runner.invoke(app, ["projects"])
        assert result.exit_code == 0
        assert "Registered Projects" in result.output


def test_multi_project_mcp(mcp_fixture):
    _, handlers = mcp_fixture
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        proj_a = Path(tmpdir) / "project_alpha"
        proj_b = Path(tmpdir) / "project_beta"

        # Record in Project Alpha
        handlers.handle_memory_add(
            content="Alpha architecture decision",
            type="architecture",
            project=str(proj_a),
        )

        # Record in Project Beta
        handlers.handle_memory_add(
            content="Beta hack workaround",
            type="hack",
            project=str(proj_b),
        )

        # Search scoped to Project Alpha
        search_a = handlers.handle_memory_search("Alpha", project=str(proj_a))
        assert search_a["count"] == 1
        assert "Alpha" in search_a["formatted"]

        # Search Alpha in Project Beta should be empty
        search_b = handlers.handle_memory_search("Alpha", project=str(proj_b))
        assert search_b["count"] == 0

        # List projects
        projects_res = handlers.handle_memory_projects()
        assert projects_res["count"] >= 1



def test_delete_and_clear_mcp(mcp_fixture):
    _, handlers = mcp_fixture
    # Add memory
    add_res = handlers.handle_memory_add(content="Delete test memory", type="decision")
    node_id = add_res["id"]

    # Delete memory
    del_res = handlers.handle_memory_delete(node_id)
    assert del_res["success"] is True

    # Check not found
    get_res = handlers.handle_memory_get(node_id)
    assert get_res["found"] is False

    # Clear memories
    clear_res = handlers.handle_memory_clear()
    assert clear_res["success"] is True


def test_delete_cli_command():
    runner = CliRunner()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_dir = Path(tmpdir) / "cli_del_test"

        runner.invoke(app, ["init", "--dir", str(test_dir)])
        runner.invoke(app, ["remember", "Memory to delete via CLI", "--type", "decision", "--project", str(test_dir)])

        db_path = Config.get_db_path(test_dir)
        storage = MemoryStorage(db_path)
        memories = storage.get_all()
        assert len(memories) == 1
        node_id = memories[0].id

        # Delete with --yes and --project flag
        del_result = runner.invoke(app, ["delete", node_id, "--yes", "--project", str(test_dir)])
        assert del_result.exit_code == 0
        assert "Successfully deleted" in del_result.output


def test_memory_add_strict_schema():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_dir = Path(tmpdir) / "strict_test"
        db_path = Config.get_db_path(test_dir)
        storage = MemoryStorage(db_path)
        handlers = MemoryMCPHandlers(default_storage=storage)

        # 1. Valid call with required content
        res = handlers.handle_memory_add(
            content="Cloud SQL multi-region failover",
            type="architecture",
            tags=["cloud-sql", "deployment"],
            impact="high",
        )
        assert res["success"] is True
        node_id = res["id"]

        get_res = handlers.handle_memory_get(node_id)
        assert get_res["found"] is True
        assert get_res["memory"]["type"] == "architecture"
        assert "Cloud SQL" in get_res["memory"]["content"]

        # 2. FastMCP server tool execution with required content
        server = create_mcp_server(storage)
        tool_fn = None
        for tool in server._tool_manager.list_tools():
            if tool.name == "memory_add":
                tool_fn = tool.fn
                break
        if tool_fn:
            result_str = tool_fn(
                content="Workaround for connection pooling",
                type="hack",
                tags=["db"],
            )
            assert "recorded" in result_str.lower()


def test_orphan_warning_and_memory_link():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_dir = Path(tmpdir) / "orphan_test"
        db_path = Config.get_db_path(test_dir)
        storage = MemoryStorage(db_path)
        handlers = MemoryMCPHandlers(default_storage=storage)

        # 1. Add an initial error memory
        err_res = handlers.handle_memory_add(
            content="SQLite database locked error on concurrent writes in multi-threaded setup",
            summary="SQLite database locked error",
            title="Database Locked Exception",
            type="error",
            tags=["sqlite", "database", "concurrency"],
            scope=["src/core/storage.py"],
        )
        assert err_res["success"] is True
        error_id = err_res["id"]

        # 2. Add a decision in same scope/tags with no parents provided - should trigger candidate detection & warning
        dec_res = handlers.handle_memory_add(
            content="Add SQLite connection locking and retry mechanism for storage layer",
            summary="Add SQLite lock handling",
            title="SQLite Connection Locking",
            type="decision",
            tags=["sqlite", "concurrency"],
            scope=["src/core/storage.py"],
        )
        assert dec_res["success"] is True
        decision_id = dec_res["id"]
        # Top score >= 0.50 should auto-link, or provide suggested parents & notice
        assert (error_id in dec_res["parents"]) or ("TACIT GRAPH NOTICE" in dec_res["message"] or len(dec_res.get("suggested_parents", [])) > 0)

        # 3. Test explicit linking via handle_memory_link
        link_res = handlers.handle_memory_link(
            child_id=decision_id,
            parent_id=error_id,
            relation="derives_from",
            reason="Decision directly fixes SQLite lock error",
        )
        assert link_res["success"] is True

        # 4. Verify updated parent edge
        updated_node = storage.get_memory(decision_id)
        assert error_id in updated_node.parents


def test_serve_when_already_running(monkeypatch):
    from unittest.mock import patch
    runner = CliRunner()

    with patch("src.export.preview_server.MarkdownPreviewServer.is_tacit_server_running", return_value=True):
        result = runner.invoke(app, ["serve", "--no-open"])
        assert result.exit_code == 0
        assert "A Tacit server instance is already running at" in result.output

def test_project_root_parent_and_alias_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        sokosupa_parent = Path(tmpdir) / "Sokosupa"
        workspace = sokosupa_parent / "sokosupa.com"
        workspace.mkdir(parents=True)
        (workspace / ".tacit").mkdir()

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(workspace)
            # Passing parent folder name "Sokosupa"
            assert Config.find_project_root("Sokosupa") == workspace.resolve()
            # Passing lowercase "sokosupa"
            assert Config.find_project_root("sokosupa") == workspace.resolve()
            # Passing workspace folder name "sokosupa.com"
            assert Config.find_project_root("sokosupa.com") == workspace.resolve()
            # Passing None
            assert Config.find_project_root(None) == workspace.resolve()
        finally:
            os.chdir(orig_cwd)



