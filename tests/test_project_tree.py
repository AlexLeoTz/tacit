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
    assert "stored description" in rendered


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
# The file table: metadata + description per file
# ---------------------------------------------------------------------------

def test_every_file_gets_a_row_with_mechanical_facts(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)
    (workspace / "backend" / "app" / "Models" / "Film.php").write_text(
        "\n".join(["<?php"] * 1500), encoding="utf-8"
    )

    row = project_tree.set_file_row(
        workspace, store_dir, "backend/app/Models/Film.php",
        description="Eloquent model for films; casts the status enum", by="agent-x",
    )

    assert row["lines"] == 1500
    assert row["language"] == "PHP"
    assert row["bytes"] > 0
    assert len(row["hash"]) == 64
    assert row["description"] == "Eloquent model for films; casts the status enum"
    assert row["by"] == "agent-x"
    assert row["updated_at"] > 0
    assert row["analyzed_at"] > 0


def test_the_map_shows_lines_and_description(workspace, store_dir):
    (workspace / "backend" / "app" / "Models" / "Film.php").write_text(
        "\n".join(["<?php"] * 12400), encoding="utf-8"
    )
    project_tree.refresh_snapshot(workspace, store_dir)
    project_tree.set_file_row(
        workspace, store_dir, "backend/app/Models/Film.php",
        description="contains the payment logic: gateway calls and refunds",
    )

    rendered = project_tree.render_stored(workspace, store_dir)

    assert "(12.4k LOC) # contains the payment logic: gateway calls and refunds" in rendered
    assert "lines of code" in rendered, "the legend explains the annotation"


def test_pending_lists_undescribed_and_unrowed_files(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)

    res = project_tree.pending_files(workspace, store_dir, limit=50)

    paths = {entry["path"] for entry in res["files"]}
    assert ".env" in paths
    assert res["total_pending"] == res["total_files"]
    assert res["described"] == 0
    # Facts are precomputed so the agent only has to write prose.
    assert all("lines" in entry and "hash" in entry for entry in res["files"])


def test_a_file_with_no_row_is_pending_and_then_complete(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)
    target = "backend/app/Models/Film.php"

    project_tree.update_file_rows(
        workspace, store_dir,
        [{"path": target, "description": "Eloquent model for films"}],
        by="agent-a",
    )
    row = project_tree.load_file_table(store_dir)[target]
    assert row["by"] == "agent-a"

    # Everything else is still pending, but this file is not.
    res = project_tree.pending_files(workspace, store_dir, limit=50)
    assert target not in {entry["path"] for entry in res["files"]}


def test_a_changed_file_becomes_stale(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)
    target = "frontend/src/main.tsx"
    project_tree.update_file_rows(
        workspace, store_dir, [{"path": target, "description": "React entry point"}]
    )

    assert target not in {e["path"] for e in project_tree.pending_files(workspace, store_dir, limit=50)["files"]}

    (workspace / "frontend" / "src" / "main.tsx").write_text(
        "export {}\nexport const added = 1\n", encoding="utf-8"
    )
    pending = project_tree.pending_files(workspace, store_dir, limit=50)

    entry = next(e for e in pending["files"] if e["path"] == target)
    assert "content changed" in entry["reasons"]
    assert entry["current_description"] == "React entry point"


def test_batch_update_skips_bad_paths_without_losing_the_batch(workspace, store_dir):
    project_tree.refresh_snapshot(workspace, store_dir)

    res = project_tree.update_file_rows(
        workspace, store_dir,
        [
            {"path": "backend/app/Models/Film.php", "description": "Model"},
            {"path": "does/not/exist.php", "description": "Nope"},
            {"path": ".env", "description": "Local environment values"},
        ],
    )

    assert res["count"] == 2
    assert [error["path"] for error in res["errors"]] == ["does/not/exist.php"]
    assert set(project_tree.load_file_table(store_dir)) == {
        "backend/app/Models/Film.php", ".env"
    }


def test_refresh_recomputes_facts_without_dropping_descriptions(workspace, store_dir):
    target = "backend/app/Models/Film.php"
    project_tree.refresh_snapshot(workspace, store_dir)
    project_tree.set_file_row(workspace, store_dir, target, description="Model", by="agent-a")

    (workspace / target).write_text("\n".join(["<?php"] * 300), encoding="utf-8")
    project_tree.set_file_row(workspace, store_dir, target)  # facts only

    row = project_tree.load_file_table(store_dir)[target]
    assert row["lines"] == 300
    assert row["description"] == "Model"
    assert row["by"] == "agent-a"


def test_stats_summarise_the_table(workspace, store_dir):
    snapshot = project_tree.refresh_snapshot(workspace, store_dir)
    project_tree.update_file_rows(
        workspace, store_dir, [{"path": ".env", "description": "Local environment values"}]
    )

    summary = project_tree.file_table_stats(workspace, store_dir)

    # Derived from the map rather than hard-coded, so adding a file to the
    # fixture cannot silently make this assertion meaningless.
    expected_files = len(project_tree.snapshot_files(snapshot))
    assert summary["files"] == expected_files
    assert summary["rows"] == 1
    assert summary["described"] == 1
    assert summary["undescribed"] == expected_files - 1
    assert summary["total_lines"] > 0
    assert "PHP" in summary["languages"]


def test_prune_drops_rows_for_deleted_files(workspace, store_dir):
    project_tree.set_file_row(workspace, store_dir, ".env", description="Env values")
    project_tree.set_file_row(workspace, store_dir, ".gitignore", description="Ignore list")
    (workspace / ".env").unlink()

    removed = project_tree.prune_file_table(workspace, store_dir)

    assert removed == [".env"]
    assert list(project_tree.load_file_table(store_dir)) == [".gitignore"]


def test_line_counts_are_formatted_compactly():
    assert project_tree.format_lines(999) == "999"
    assert project_tree.format_lines(12400) == "12.4k"
    assert project_tree.format_lines(1_250_000) == "1.2M"


def test_a_legacy_gists_file_is_migrated_into_the_table(workspace, store_dir):
    legacy = project_tree.gists_path(store_dir)
    legacy.write_text(
        '{"backend/app/Models/Film.php": {"gist": "Legacy note", "updated_at": 1700000000.0, "by": "old-agent"}}',
        encoding="utf-8",
    )

    rows = project_tree.load_file_table(store_dir)

    assert rows["backend/app/Models/Film.php"]["description"] == "Legacy note"
    assert rows["backend/app/Models/Film.php"]["by"] == "old-agent"
    assert rows["backend/app/Models/Film.php"]["migrated_from"] == "gists.json"


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


def test_mcp_pending_and_batch_update_fill_the_table(workspace, store_dir):
    """The workflow the agent rules describe: list, then write many rows at once."""
    handlers = MemoryMCPHandlers(project_root=workspace)

    pending = handlers.handle_project_files_pending(limit=10)
    assert pending["total_pending"] > 0
    assert "project_files_update" in pending["formatted"]
    paths = [entry["path"] for entry in pending["files"]]

    written = handlers.handle_project_files_update(
        entries=[{"path": path, "description": f"Describes {path}"} for path in paths],
        by="agent-b",
    )

    assert written["count"] == len(paths)
    assert "still pending" in written["formatted"] or "now complete" in written["formatted"]
    rows = project_tree.load_file_table(store_dir)
    assert all(rows[path]["by"] == "agent-b" for path in paths)

    again = handlers.handle_project_files_pending(limit=10)
    assert "current" in again["formatted"] or all(
        entry["path"] not in paths for entry in again["files"]
    )


def test_mcp_pending_reports_a_bad_path_per_entry(workspace, store_dir):
    handlers = MemoryMCPHandlers(project_root=workspace)

    res = handlers.handle_project_files_update(
        entries=[{"path": "nope/missing.php", "description": "x"}]
    )

    assert res["count"] == 0
    assert "REJECTED" in res["formatted"]


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


def test_agent_rules_document_the_file_table_workflow():
    from src.core.agent_rules import AGENT_RULE_CONTENT

    # Filling must be described as a batched operation, and rows must be kept
    # true after a change — otherwise the table rots into a misleading map.
    assert "project_files_pending" in AGENT_RULE_CONTENT
    assert "project_files_update" in AGENT_RULE_CONTENT
    assert "parallel batches" in AGENT_RULE_CONTENT
    assert "refresh its row" in AGENT_RULE_CONTENT


def test_agent_rules_document_the_chronicle():
    from src.core.agent_rules import AGENT_RULE_CONTENT

    assert "memory_chronicle" in AGENT_RULE_CONTENT
    assert "oldest-first" in AGENT_RULE_CONTENT


def test_cli_files_pending_and_set(workspace):
    CliRunner().invoke(app, ["structure", "--refresh", "--project", str(workspace)])

    pending = CliRunner().invoke(app, ["files", "--pending", "--project", str(workspace)])
    assert pending.exit_code == 0
    assert "need a row" in pending.stdout

    written = CliRunner().invoke(
        app,
        ["files", "--set", "frontend/src/main.tsx", "--description",
         "React entry point that mounts the router", "--project", str(workspace)],
    )
    assert written.exit_code == 0
    assert "Row updated" in written.stdout

    rows = project_tree.load_file_table(workspace / ".tacit")
    assert rows["frontend/src/main.tsx"]["description"] == "React entry point that mounts the router"
    assert rows["frontend/src/main.tsx"]["lines"] > 0


def test_cli_files_stats_and_prune(workspace):
    project_tree.set_file_row(workspace, workspace / ".tacit", ".env", description="Env values")

    stats = CliRunner().invoke(app, ["files", "--stats", "--project", str(workspace)])
    assert stats.exit_code == 0
    assert "File Table" in stats.stdout

    (workspace / ".env").unlink()
    pruned = CliRunner().invoke(app, ["files", "--prune", "--project", str(workspace)])
    assert pruned.exit_code == 0
    assert "Removed 1 stale row" in pruned.stdout


def test_cli_files_refresh_recomputes_lines(workspace, store_dir):
    target = "backend/app/Models/Film.php"
    project_tree.refresh_snapshot(workspace, store_dir)
    project_tree.set_file_row(workspace, store_dir, target, description="Model")

    (workspace / target).write_text("\n".join(["<?php"] * 400), encoding="utf-8")
    result = CliRunner().invoke(app, ["files", "--refresh", "--project", str(workspace)])

    assert result.exit_code == 0
    assert project_tree.load_file_table(store_dir)[target]["lines"] == 400
    assert project_tree.load_file_table(store_dir)[target]["description"] == "Model"

