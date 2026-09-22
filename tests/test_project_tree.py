"""The project-structure map: names and nesting only, plus per-file gists.

A new session should be able to learn the layout of a multi-repo workspace
(backend + frontend) in one call, without reading a single source file.
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core import project_tree
from src.core.bootstrap import BootstrapEngine
from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_project_tree_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def workspace(tmp_dir):
    """A parent directory holding two repositories, plus noise to ignore."""
    root = tmp_dir / "shop"
    (root / "backend" / "app" / "Models").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "backend" / ".git").mkdir()
    (root / "frontend" / ".git").mkdir()
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "backend" / "app" / "Models" / "Film.php").write_text("<?php", encoding="utf-8")
    (root / "frontend" / "src" / "main.tsx").write_text("export {}", encoding="utf-8")
    (root / ".env").write_text("APP_KEY=1", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    return root


@pytest.fixture
def store_dir(workspace):
    store = workspace / ".tacit"
    (store).mkdir(parents=True, exist_ok=True)
    project_tree.update_tree_settings(store, enabled=True)
    return store


@pytest.fixture(autouse=True)
def no_gemini_prompt(monkeypatch):
    """`tacit init` asks about embeddings when a key is present; keep it silent."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("TACIT_PROJECT", raising=False)


# ---------------------------------------------------------------------------
# Discovery and snapshot building
# ---------------------------------------------------------------------------

def test_discovery_finds_each_git_repository(workspace):
    assert project_tree.discover_repos(workspace) == ["backend", "frontend"]


def test_discovery_ignores_dependency_trees(workspace):
    (workspace / "node_modules" / "left-pad" / ".git").mkdir()

    assert project_tree.discover_repos(workspace) == ["backend", "frontend"]


def test_a_single_repository_is_reported_as_the_root(tmp_dir):
    root = tmp_dir / "solo"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()

    assert project_tree.discover_repos(root) == ["."]


def test_snapshot_keeps_names_and_never_reads_source(workspace):
    snapshot = project_tree.build_snapshot(workspace, {"max_depth": 5})
    rendered = project_tree.render_tree(snapshot)

    assert "Film.php" in rendered
    assert "main.tsx" in rendered
    assert ".env" in rendered, "configuration files are part of the layout"
    assert "node_modules" not in rendered
    assert "<?php" not in rendered and "APP_KEY" not in rendered, "never source or secrets"
    assert snapshot["repos"] == ["backend", "frontend"]
    assert snapshot["truncated"] is False


def test_max_depth_is_respected(workspace):
    snapshot = project_tree.build_snapshot(workspace, {"max_depth": 2})
    rendered = project_tree.render_tree(snapshot)

    assert "backend" in rendered
    assert "Film.php" not in rendered, "depth 2 stops above the file"


def test_entry_budget_truncates_instead_of_hanging(workspace):
    snapshot = project_tree.build_snapshot(workspace, {"max_entries": 2})
    rendered = project_tree.render_tree(snapshot)

    assert snapshot["truncated"] is True
    assert "capped at 2 entries" in rendered


def test_settings_round_trip_through_the_store(store_dir):
    assert project_tree.tree_settings(store_dir)["max_depth"] == project_tree.DEFAULT_MAX_DEPTH

    project_tree.update_tree_settings(store_dir, max_depth=2, repos=["backend"])
    settings = project_tree.tree_settings(store_dir)

    assert settings["max_depth"] == 2
    assert settings["repos"] == ["backend"]
    assert settings["enabled"] is True
    # The config must be plain JSON inside the store, so `tacit move` carries it.
    assert json.loads((store_dir / "config.json").read_text(encoding="utf-8"))["project_tree"]


def test_pinned_repos_override_discovery(store_dir):
    project_tree.update_tree_settings(store_dir, repos=["backend", "frontend"])

    snapshot = project_tree.build_snapshot(store_dir.parent, project_tree.tree_settings(store_dir))

    assert snapshot["repos"] == ["backend", "frontend"]


# ---------------------------------------------------------------------------
# Gists
# ---------------------------------------------------------------------------

def test_gists_annotate_the_rendered_map(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)

    project_tree.set_gist(store_dir, "backend/app/Models/Film.php", "Eloquent model for films")
    rendered = project_tree.render_stored(workspace, store_dir)

    assert "Film.php   # Eloquent model for films" in rendered
    assert "stored file gist" in rendered


def test_gist_survives_windows_style_paths(workspace, store_dir):
    stored = project_tree.set_gist(store_dir, r"backend\app\Models\Film.php", "Model")

    assert stored is not None
    assert "backend/app/Models/Film.php" in project_tree.load_gists(store_dir)


def test_an_empty_gist_removes_the_entry(workspace, store_dir):
    project_tree.set_gist(store_dir, "backend/app/Models/Film.php", "Model")
    project_tree.set_gist(store_dir, "backend/app/Models/Film.php", "")

    assert project_tree.load_gists(store_dir) == {}


def test_gists_for_deleted_files_are_pruned(store_dir):
    project_tree.set_gist(store_dir, "gone.php", "stale")
    project_tree.set_gist(store_dir, "kept.php", "fresh")

    removed = project_tree.prune_gists(store_dir, ["kept.php"])

    assert removed == ["gone.php"]
    assert list(project_tree.load_gists(store_dir)) == ["kept.php"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_init_captures_the_structure_by_default(workspace):
    result = CliRunner().invoke(app, ["init", "--dir", str(workspace), "--structure"])

    assert result.exit_code == 0
    assert "Project structure captured" in result.stdout
    snapshot = project_tree.load_snapshot(workspace / ".tacit")
    assert snapshot is not None and snapshot["entry_count"] > 0


def test_init_can_opt_out_of_the_structure(workspace):
    result = CliRunner().invoke(app, ["init", "--dir", str(workspace), "--no-structure"])

    assert result.exit_code == 0
    assert project_tree.load_snapshot(workspace / ".tacit") is None
    assert project_tree.tree_settings(workspace / ".tacit")["enabled"] is False


def test_structure_refresh_picks_up_new_files(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)
    (workspace / "backend" / "app" / "Actions").mkdir()
    (workspace / "backend" / "app" / "Actions" / "StoreFilm.php").write_text("<?php", encoding="utf-8")

    result = CliRunner().invoke(app, ["structure", "--project", str(workspace), "--refresh"])

    assert result.exit_code == 0
    assert "Snapshot updated" in result.stdout
    assert "StoreFilm.php" in result.stdout


def test_structure_prints_the_stored_map(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)

    result = CliRunner().invoke(app, ["structure", "--project", str(workspace)])

    assert result.exit_code == 0
    assert "- backend/ *" in result.stdout
    assert "- Film.php" in result.stdout


def test_structure_without_a_snapshot_explains_how_to_make_one(workspace):
    result = CliRunner().invoke(app, ["structure", "--project", str(workspace)])

    assert result.exit_code == 0
    # The console wraps long lines, so compare on collapsed whitespace.
    flat = " ".join(result.stdout.split())
    assert "No project structure has been captured" in flat
    assert "tacit structure --refresh" in flat


def test_structure_can_list_discovered_repos(workspace, store_dir):
    result = CliRunner().invoke(app, ["structure", "--repos", "--project", str(workspace)])

    assert result.exit_code == 0
    assert "backend" in result.stdout and "frontend" in result.stdout


def test_structure_set_repos_pins_the_tracked_projects(workspace, store_dir):
    result = CliRunner().invoke(
        app, ["structure", "--set-repos", "backend", "--project", str(workspace)]
    )

    assert result.exit_code == 0
    assert project_tree.tree_settings(store_dir)["repos"] == ["backend"]


def test_structure_can_be_disabled_and_re_enabled(workspace, store_dir):
    assert CliRunner().invoke(
        app, ["structure", "--disable", "--project", str(workspace)]
    ).exit_code == 0
    assert project_tree.tree_settings(store_dir)["enabled"] is False

    assert CliRunner().invoke(
        app, ["structure", "--enable", "--project", str(workspace)]
    ).exit_code == 0
    assert project_tree.tree_settings(store_dir)["enabled"] is True


def test_refresh_re_enables_a_disabled_snapshot(workspace, store_dir):
    """Asking for a refresh is a request for the map to exist."""
    project_tree.update_tree_settings(store_dir, enabled=False)

    result = CliRunner().invoke(app, ["structure", "--refresh", "--project", str(workspace)])

    assert result.exit_code == 0
    assert project_tree.tree_settings(store_dir)["enabled"] is True
    assert "disabled for this workspace" not in result.stdout


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------

def test_mcp_project_structure_refreshes_and_renders(workspace, store_dir):
    handlers = MemoryMCPHandlers(project_root=workspace)

    res = handlers.handle_project_structure(refresh=True)

    assert res["count"] > 0
    assert "- backend/ *" in res["formatted"]
    assert res["repos"] == ["backend", "frontend"]
    assert "disabled for this workspace" not in res["formatted"]


def test_mcp_refresh_enables_capture_in_a_fresh_store(workspace):
    """A workspace whose store has no config yet must not render a live map and then call itself disabled."""
    handlers = MemoryMCPHandlers(project_root=workspace)

    res = handlers.handle_project_structure(refresh=True)

    assert project_tree.tree_settings(workspace / ".tacit")["enabled"] is True
    assert "disabled for this workspace" not in res["formatted"]


def test_mcp_project_structure_narrows_to_a_path(workspace, store_dir):
    handlers = MemoryMCPHandlers(project_root=workspace)
    handlers.handle_project_structure(refresh=True)

    res = handlers.handle_project_structure(path="backend/app")

    assert "Models/" in res["formatted"]
    assert "main.tsx" not in res["formatted"]


def test_mcp_project_gist_is_shown_in_the_map(workspace, store_dir):
    handlers = MemoryMCPHandlers(project_root=workspace)
    handlers.handle_project_structure(refresh=True)

    written = handlers.handle_project_gist(
        path="backend/app/Models/Film.php", gist="Eloquent model for films, casts status enum"
    )
    assert written["success"] is True

    rendered = handlers.handle_project_structure()
    assert "Eloquent model for films" in rendered["formatted"]


def test_mcp_project_gist_rejects_an_unknown_file(workspace, store_dir):
    handlers = MemoryMCPHandlers(project_root=workspace)

    res = handlers.handle_project_gist(path="backend/app/Nope.php", gist="x")

    assert res["success"] is False
    assert "No such file" in res["message"]


def test_briefing_points_at_the_project_map(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)
    storage = MemoryStorage(store_dir / "memory.db")
    from src.utils.config import Config

    res = BootstrapEngine.generate_briefing(storage=storage)

    assert "Project map:" in res["formatted"]
    assert "call project_structure" in res["formatted"]


def test_briefing_has_no_map_line_when_disabled(workspace, store_dir):
    project_tree.update_tree_settings(store_dir, enabled=False)
    project_tree.refresh_snapshot(workspace, store_dir)
    storage = MemoryStorage(store_dir / "memory.db")

    res = BootstrapEngine.generate_briefing(storage=storage)

    assert "Project map:" not in res["formatted"]


# ---------------------------------------------------------------------------
# Agent rules
# ---------------------------------------------------------------------------

def test_agent_rules_document_the_structure_tools():
    from src.core.agent_rules import AGENT_RULE_CONTENT

    assert "project_structure" in AGENT_RULE_CONTENT
    assert "project_gist" in AGENT_RULE_CONTENT
