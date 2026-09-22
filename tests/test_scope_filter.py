"""Scope is a FILTER, and a memory store can only ever belong to one project.

Two failures motivated this file:

1. A briefing mixed memories from several unrelated repositories, because the
   MCP server resolved "the project" to the home directory and silently created
   a store there, which every workspace beneath it then shared.
2. ``scope_hint`` only boosted matching nodes by 25%, so an agent that said "I am
   working in backend/app" still got frontend memories ranked above its own.
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core.bootstrap import BootstrapEngine
from src.core.memory_node import MemoryNode, validate_scope_paths
from src.core.storage import MemoryStorage
from src.mcp.handlers import MemoryMCPHandlers
from src.utils.config import Config, ProjectRootError
from src.utils.scope import node_matches_scope, scope_is_project_wide, scope_matches


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_scope_filter_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def project(tmp_dir):
    """A realistic two-repo workspace root."""
    root = tmp_dir / "gramu"
    (root / "backend" / "app" / "Livewire" / "Admin").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


@pytest.fixture
def storage(project):
    return MemoryStorage(project / ".tacit" / "memory.db")


@pytest.fixture(autouse=True)
def fast_writes(monkeypatch):
    from src.search.embeddings import EmbeddingService

    monkeypatch.setattr(Config, "DUAL_WRITE", False, raising=False)
    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))


def _node(storage, title, scope, impact="medium"):
    node = MemoryNode(
        id=str(uuid.uuid4()),
        title=title,
        summary=f"{title} summary",
        content=f"{title} body",
        type="decision",
        tags=["t"],
        scope=scope,
        impact=impact,
        timestamp=datetime.now(timezone.utc).timestamp(),
    )
    assert storage.add_memory(node) is True
    return node


# ---------------------------------------------------------------------------
# Root guards: a store is never invented in a container directory
# ---------------------------------------------------------------------------

def test_home_and_drive_roots_are_containers(tmp_dir):
    assert Config.is_container_dir(Path.home()) is True
    assert Config.is_container_dir(Path.home() / "Desktop") is True
    drive_root = Path(Path.cwd().anchor)
    assert Config.is_container_dir(drive_root) is True


def test_a_repository_is_not_a_container(project):
    assert Config.is_container_dir(project) is False
    assert Config.has_project_marker(project) is True


def test_require_project_root_refuses_the_home_directory():
    """The exact accident: an MCP client launched with CWD = the home folder."""
    with pytest.raises(ProjectRootError) as excinfo:
        Config.require_project_root(Path.home(), explicit=False)

    message = str(excinfo.value)
    assert "container directory" in message
    assert "--project" in message and "tacit init" in message


def test_require_project_root_refuses_an_unidentified_directory(tmp_dir):
    """A store invented in a marker-less folder becomes an ancestor marker for
    everything created below it, which is the same leak in slow motion."""
    plain = tmp_dir / "not-a-project"
    plain.mkdir()

    with pytest.raises(ProjectRootError) as excinfo:
        Config.require_project_root(plain, explicit=False)

    assert "no .tacit, .git, pyproject.toml or package.json" in str(excinfo.value)


def test_init_may_turn_an_unidentified_directory_into_a_project(tmp_dir):
    """`tacit init` is the one command whose purpose is to create the marker."""
    plain = tmp_dir / "brand-new"
    plain.mkdir()

    result = CliRunner().invoke(app, ["init", "--dir", str(plain), "--no-structure"])

    assert result.exit_code == 0
    assert (plain / ".tacit" / "memory.db").exists()


def test_other_commands_refuse_an_unidentified_directory(tmp_dir, monkeypatch):
    """Simulates a client whose working directory is inside no project at all."""
    plain = tmp_dir / "not-a-project"
    plain.mkdir()
    monkeypatch.setattr(
        Config, "find_project_root", classmethod(lambda cls, start=None: plain)
    )
    monkeypatch.delenv("TACIT_PROJECT", raising=False)

    result = CliRunner().invoke(app, ["remember", "something worth keeping", "--title", "A title"])

    assert result.exit_code == 1
    flat = " ".join(result.stdout.split())
    assert "No project to store memories in" in flat
    assert "no .tacit, .git, pyproject.toml or package.json" in flat
    assert not (plain / ".tacit").exists()


def test_an_explicitly_named_project_root_is_always_honoured():
    """`tacit move --dir` and TACIT_PROJECT must never be second-guessed."""
    assert Config.require_project_root(Path.home(), explicit=True) == Path.home().resolve()


def test_ensure_directories_refuses_to_create_a_store_in_a_container(monkeypatch):
    monkeypatch.setattr(Config, "find_project_root", classmethod(lambda cls, p=None: Path.home()))
    monkeypatch.delenv("TACIT_PROJECT", raising=False)

    with pytest.raises(ProjectRootError):
        Config.ensure_directories()


def test_register_project_skips_container_and_missing_directories(tmp_dir, monkeypatch, project):
    registry = tmp_dir / "tacit_projects.json"
    monkeypatch.setattr(Config, "REGISTRY_FILE", registry)

    Config.register_project(Path.home())
    Config.register_project(tmp_dir / "does-not-exist")
    Config.register_project(project)

    stored = json.loads(registry.read_text(encoding="utf-8"))
    assert list(stored) == ["gramu"]


def test_registry_listing_drops_junk_entries(tmp_dir, monkeypatch, project):
    registry = tmp_dir / "tacit_projects.json"
    registry.write_text(
        json.dumps(
            {
                "DELL": str(Path.home()),
                "System32": str(Path(Path.cwd().anchor) / "Windows" / "System32"),
                "gone": str(tmp_dir / "deleted-long-ago"),
                "gramu": str(project),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Config, "REGISTRY_FILE", registry)

    listed = Config.list_registered_projects()

    assert listed == {"gramu": str(project)}


# ---------------------------------------------------------------------------
# Scope matching / filtering semantics
# ---------------------------------------------------------------------------

def test_a_directory_hint_matches_files_beneath_it_and_vice_versa():
    stored = ["backend/app/Livewire/Admin/FilmManager.php"]

    assert scope_matches(stored, ["backend/app"]) is True
    assert scope_matches(stored, ["backend/app/Livewire/Admin/FilmManager.php"]) is True
    assert scope_matches(stored, ["backend/app/Models/Film.php"]) is False
    assert scope_matches(stored, ["frontend/src"]) is False


def test_a_bare_filename_hint_matches_the_file_it_names():
    stored = ["backend/app/Livewire/Admin/FilmManager.php"]

    assert scope_matches(stored, ["FilmManager.php"]) is True
    assert scope_matches(stored, ["FilmShow.php"]) is False


def test_matching_is_segment_wise_so_prefixes_do_not_collide():
    """`app` must not match `myapp`, which the old substring test got wrong."""
    assert scope_matches(["src/myapp/main.ts"], ["app"]) is False
    assert scope_matches(["src/app/main.ts"], ["app"]) is True


def test_no_hints_means_the_whole_workspace(project):
    assert node_matches_scope(["frontend/src"], [], project_root=project) is True


def test_project_wide_scope_survives_every_filter(project):
    assert scope_is_project_wide(["gramu"], project_root=project) is True
    assert scope_is_project_wide([], project_root=project) is True
    assert scope_is_project_wide(["/"], project_root=project) is True
    assert scope_is_project_wide(["payment-portal"], project_root=project) is False

    assert node_matches_scope(["gramu"], ["backend/app"], project_root=project) is True
    assert node_matches_scope(["payment-portal"], ["backend/app"], project_root=project) is False


# ---------------------------------------------------------------------------
# The briefing only ranks what the scope filter kept
# ---------------------------------------------------------------------------

def test_briefing_excludes_memories_from_another_subsystem(storage, project):
    _node(storage, "Backend film manager refactor", ["backend/app/Livewire/Admin/FilmManager.php"])
    _node(storage, "Frontend download card", ["frontend/src"])
    _node(storage, "Workspace-wide convention", ["gramu"])

    res = BootstrapEngine.generate_briefing(
        storage=storage, scope_hint=["backend/app"], budget=4000
    )

    titles = [entry["title"] for entry in res["full"]]
    for items in res["brief"].values():
        titles.extend(entry["title"] for entry in items)

    assert "Backend film manager refactor" in titles
    assert "Workspace-wide convention" in titles, "project-wide knowledge is never filtered out"
    assert "Frontend download card" not in titles


def test_an_empty_scoped_briefing_says_why_instead_of_showing_other_projects(storage):
    _node(storage, "Frontend download card", ["frontend/src"])

    res = BootstrapEngine.generate_briefing(
        storage=storage, scope_hint=["backend/app"], budget=4000
    )

    assert res["count"] == 0
    assert "No active memories are scoped to [backend/app]" in res["formatted"]
    assert "Retry without scope_hint" in res["formatted"]


def test_search_filters_instead_of_boosting(storage):
    _node(storage, "Cloudflare origin rule for gramutz", ["backend/app"])
    _node(storage, "Cloudflare origin rule for the storefront", ["frontend/src"])

    results = storage.search_hybrid("cloudflare origin rule", limit=10, mode="keyword")
    assert len(results) == 2, "unscoped search reads the whole workspace"

    scoped = storage.search_hybrid(
        "cloudflare origin rule", limit=10, mode="keyword", scope_hint=["frontend/src"]
    )
    titles = [item["node"].title for item in scoped]
    assert titles == ["Cloudflare origin rule for the storefront"]


def test_grep_filters_by_scope(storage):
    _node(storage, "Cloudflare origin rule for gramutz", ["backend/app"])
    _node(storage, "Cloudflare origin rule for the storefront", ["frontend/src"])

    assert len(storage.grep_memories("cloudflare")) == 2
    scoped = storage.grep_memories("cloudflare", scope_hint=["backend/app"])
    assert [node.title for node in scoped] == ["Cloudflare origin rule for gramutz"]


# ---------------------------------------------------------------------------
# Write path: every node carries a scope
# ---------------------------------------------------------------------------

def test_a_memory_added_without_a_scope_becomes_project_wide(storage, project):
    handlers = MemoryMCPHandlers(storage, project_root=project)

    res = handlers.handle_memory_add(
        content="Body",
        title="Postgres connection pooling defaults",
        summary="Pooled connections",
        type="decision",
    )

    assert res["success"] is True
    assert res["scope"] == [project.name]
    assert "TACIT SCOPE NOTICE" in res["message"]

    stored = storage.get_memory(res["id"])
    assert stored.scope == [project.name]


def test_scope_paths_are_validated_against_the_target_project(project, monkeypatch):
    monkeypatch.delenv("TACIT_NO_PATH_VALIDATION", raising=False)

    validate_scope_paths(["backend/app"], str(project))
    validate_scope_paths([project.name], str(project))

    with pytest.raises(ValueError) as excinfo:
        validate_scope_paths(["backend/app/Typoed.php"], str(project))

    message = str(excinfo.value)
    assert "do not exist under the project root" in message
    assert "the project name" in message


def test_an_invalid_scope_is_rejected_rather_than_stored_unfindable(storage, project, monkeypatch):
    monkeypatch.delenv("TACIT_NO_PATH_VALIDATION", raising=False)
    handlers = MemoryMCPHandlers(storage, project_root=project)

    res = handlers.handle_memory_add(
        content="Body",
        title="Refactor of a file that does not exist",
        summary="Typo in scope",
        scope=["backend/app/Nope.php"],
    )

    assert res["success"] is False
    assert "Memory NOT recorded" in res["message"]
    assert storage.get_count() == 0


# ---------------------------------------------------------------------------
# One server, many workspaces
# ---------------------------------------------------------------------------

def test_an_unresolved_server_reports_instead_of_guessing(project):
    """No store at all: the server must say so rather than pick a nearby one."""
    handlers = MemoryMCPHandlers(project_root=project, unresolved_reason="no workspace was identified")

    blocked = handlers.handle_memory_context()
    assert blocked["count"] == 0
    assert "no workspace was identified" in blocked["message"]

    # Naming the project explicitly still works: that is how one MCP server
    # serves several workspaces.
    explicit = handlers.handle_memory_context(project=str(project))
    assert "PROJECT BRIEFING" in explicit["formatted"]


def test_scope_hints_resolve_against_the_requested_project(storage, project, tmp_dir):
    """A foreign absolute hint must be ignored, and the local one kept relative."""
    handlers = MemoryMCPHandlers(storage, project_root=project)
    other = tmp_dir / "other-repo"
    (other / "app").mkdir(parents=True)

    hints = handlers.handle_memory_search
    res = hints(query="nothing", scope_hint=[str(other / "app")], project=str(project))

    assert res["scope"] == [], "an absolute path outside the project cannot scope it"
