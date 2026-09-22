"""Tests for `tacit move`, which relocates the .tacit store inside a project.

The store doubles as the project marker, so the move leaves a one-line pointer at
``<root>/.tacit/location`` and every read path resolves through
``Config.get_memory_dir``. These tests cover the move itself, that everything
still resolves afterwards, and the guards that keep a bad destination from
destroying data.
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core.storage import MemoryStorage
from src.utils.config import Config


@pytest.fixture
def project(tmp_dir):
    """A fresh project with one recorded memory."""
    root = tmp_dir / "proj"
    Config.ensure_directories(root)
    storage = MemoryStorage(Config.get_db_path(root))
    from src.core.memory_node import MemoryNode

    storage.add_memory(
        MemoryNode(id="11111111-2222-4333-8444-555555555555",
                   title="Store relocation probe", summary="s", content="c")
    )
    return root


@pytest.fixture
def tmp_dir():
    base = Path(__file__).resolve().parent / "_move_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_dir, monkeypatch):
    """Keep test projects out of the user's real project registry."""
    monkeypatch.setattr(Config, "REGISTRY_FILE", tmp_dir / "registry.json")


def run(*args):
    return CliRunner().invoke(app, list(args))


# ---------------------------------------------------------------------------
# Relocation
# ---------------------------------------------------------------------------

def test_move_relocates_the_store_and_writes_a_pointer(project):
    before = Config.get_memory_dir(project)
    assert before == project / ".tacit"
    assert (before / "memory.db").exists()

    result = run("move", "agent-memory", "--project", str(project))

    assert result.exit_code == 0
    after = Config.get_memory_dir(project)
    assert after == project / "agent-memory" / ".tacit"
    assert (after / "memory.db").exists()
    assert not (before / "memory.db").exists(), "the store is moved, not copied"


def test_the_pointer_records_a_relative_path(project):
    run("move", "agent-memory", "--project", str(project))

    pointer = project / ".tacit" / "location"
    assert pointer.exists()
    assert pointer.read_text(encoding="utf-8").strip() == "agent-memory/.tacit"


def test_the_marker_directory_survives_so_discovery_still_works(project):
    run("move", "agent-memory", "--project", str(project))

    # find_project_root treats a .tacit entry as the project marker.
    assert (project / ".tacit").exists()
    assert Config.find_project_root(project) == project.resolve()


def test_writes_and_reads_keep_working_after_a_move(project):
    run("move", "agent-memory", "--project", str(project))

    storage = MemoryStorage(Config.get_db_path(project))
    storage.add_memory.__self__  # sanity: storage is usable
    assert storage.get_memory("11111111-2222-4333-8444-555555555555") is not None

    result = run("recent", "--days", "1", "--project", str(project))
    assert result.exit_code == 0
    assert "Store relocation probe" in result.stdout


def test_ensure_directories_returns_the_project_root_after_a_move(project):
    """It used to derive the root from memory_dir.parent, which becomes the subfolder."""
    run("move", "agent-memory", "--project", str(project))

    assert Config.ensure_directories(project) == project.resolve()


def test_moving_back_restores_the_default_layout(project):
    run("move", "agent-memory", "--project", str(project))

    result = run("move", ".", "--project", str(project))

    assert result.exit_code == 0
    assert (project / ".tacit" / "memory.db").exists()
    assert not (project / ".tacit" / "location").exists(), "no pointer when the store is default"
    assert not (project / "agent-memory" / ".tacit").exists()
    # And the data made the round trip.
    assert MemoryStorage(Config.get_db_path(project)).get_memory(
        "11111111-2222-4333-8444-555555555555"
    ) is not None


def test_move_back_does_not_nest_the_store_in_its_own_marker(project):
    """`ensure_directories` used to recreate <root>/.tacit before the move,
    so shutil.move dropped the store inside it as <root>/.tacit/.tacit."""
    run("move", "agent-memory", "--project", str(project))

    run("move", ".", "--project", str(project))

    assert not (project / ".tacit" / ".tacit").exists()
    assert (project / ".tacit" / "memory.db").is_file()


def test_moving_twice_chains_the_pointer(project):
    run("move", "first", "--project", str(project))

    result = run("move", "second", "--project", str(project))

    assert result.exit_code == 0
    assert Config.get_memory_dir(project) == project / "second" / ".tacit"
    assert (project / "second" / ".tacit" / "memory.db").exists()
    assert not (project / "first" / ".tacit").exists()


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def test_move_refuses_a_destination_outside_the_project(project):
    result = run("move", "../elsewhere", "--project", str(project))

    assert result.exit_code == 1
    assert "inside the project root" in " ".join(result.stdout.split())
    assert (project / ".tacit" / "memory.db").exists(), "nothing was changed"


def test_move_refuses_to_nest_the_store_inside_itself(project):
    """A destination beneath the current store would move it into itself."""
    result = run("move", ".tacit/deeper", "--project", str(project))

    assert result.exit_code == 1
    assert "inside itself" in " ".join(result.stdout.split())
    assert (project / ".tacit" / "memory.db").exists()


def test_move_is_a_noop_when_already_there(project):
    result = run("move", ".", "--project", str(project))

    assert result.exit_code == 0
    assert "already at" in " ".join(result.stdout.split())
    assert (project / ".tacit" / "memory.db").exists()


def test_move_refuses_when_the_target_already_holds_a_store(project):
    occupied = project / "taken" / ".tacit"
    occupied.mkdir(parents=True)
    (occupied / "memory.db").write_text("already here", encoding="utf-8")

    result = run("move", "taken", "--project", str(project))

    assert result.exit_code == 1
    assert "already exists" in " ".join(result.stdout.split())
    assert (project / ".tacit" / "memory.db").exists(), "the original store is untouched"


def test_move_reports_a_missing_store(tmp_dir):
    empty = tmp_dir / "bare"
    empty.mkdir()

    result = run("move", "somewhere", "--project", str(empty))

    assert result.exit_code == 1
    assert "No Tacit store found" in " ".join(result.stdout.split())


# ---------------------------------------------------------------------------
# Pointer handling
# ---------------------------------------------------------------------------

def test_read_memory_location_is_none_without_a_pointer(project):
    assert Config.read_memory_location(project) is None


def test_read_memory_location_ignores_a_blank_pointer(project):
    marker = project / ".tacit"
    (marker / "location").write_text("   \n", encoding="utf-8")

    assert Config.read_memory_location(project) is None


def test_absolute_pointer_paths_are_accepted(project, tmp_dir):
    external = tmp_dir / "external-store"
    shutil.copytree(project / ".tacit", external)
    (project / ".tacit" / "location").write_text(str(external), encoding="utf-8")

    assert Config.get_memory_dir(project) == external.resolve()


def test_model_cache_follows_a_relocated_store(project, monkeypatch):
    """The offline model cache lives under the store, so it must move with it."""
    from src.search import embeddings as emb

    run("move", "agent-memory", "--project", str(project))
    monkeypatch.setattr(emb, "user_cache_dir", lambda: Path("C:/Windows/System32/tacit_nope"))

    resolved = emb.resolve_cache_dir(project)

    assert resolved == project / "agent-memory" / ".tacit" / "models"
