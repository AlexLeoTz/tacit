"""The store must survive a clone: .tacit is data, not a build artifact.

The failure this guards against is silent. A template ``.gitignore`` ignores
dot-directories (or ``*.db``), the repository is cloned on another machine, and
every memory is gone — while the code looks perfectly healthy. ``tacit init``
and MCP startup therefore re-include the store and stage it once.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.utils.git_tracking import (
    MANAGED_END,
    MANAGED_START,
    ensure_store_tracked,
    git_toplevel,
    managed_block,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "shop"
    (root / ".tacit" / "decision").mkdir(parents=True)
    (root / ".tacit" / "models").mkdir(parents=True)
    (root / ".tacit" / "memory.db").write_bytes(b"SQLite format 3\x00")
    (root / ".tacit" / "decision" / "2026-01-01_note_abcd1234.md").write_text(
        "# A decision\n", encoding="utf-8"
    )
    (root / ".tacit" / "models" / "bge.onnx").write_bytes(b"model")
    (root / ".tacit" / "memory.db-wal").write_bytes(b"wal")
    (root / ".gitignore").write_text(".tacit/\n*.db\n", encoding="utf-8")
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    assert _git(root, "init").returncode == 0
    return root


def test_a_non_repository_is_a_safe_no_op(tmp_path, monkeypatch):
    from src.utils import git_tracking

    plain = tmp_path / "plain"
    plain.mkdir()
    # The test suite itself lives inside the Tacit checkout, so a bare directory
    # here would still resolve to *this* repository. Simulate "no repo" instead.
    monkeypatch.setattr(git_tracking, "git_toplevel", lambda root: None)

    status = ensure_store_tracked(plain)

    assert status["git_repo"] is False
    assert status["tracked"] is False
    assert "not a git repository" in status["message"].lower()
    assert not (plain / ".gitignore").exists()


def test_an_ignored_store_is_reincluded_and_staged(repo):
    assert _git(repo, "check-ignore", "-q", ".tacit/memory.db").returncode == 0

    status = ensure_store_tracked(repo)

    assert status["git_repo"] is True
    assert status["ignored"] is True
    assert status["ignore_fixed"] is True
    assert status["tracked"] is True
    assert status["staged"] is True
    # The data is no longer ignored.
    assert _git(repo, "check-ignore", "-q", ".tacit/memory.db").returncode != 0
    # And it is in the index.
    tracked = _git(repo, "ls-files", "--", ".tacit").stdout
    assert ".tacit/memory.db" in tracked
    assert ".tacit/decision/2026-01-01_note_abcd1234.md" in tracked
    # Regenerable and live SQLite state stays out.
    assert "models" not in tracked
    assert "memory.db-wal" not in tracked


def test_the_gitignore_block_is_idempotent(repo):
    ensure_store_tracked(repo)
    first = (repo / ".gitignore").read_text(encoding="utf-8")

    ensure_store_tracked(repo)
    second = (repo / ".gitignore").read_text(encoding="utf-8")

    assert first == second
    assert second.count(MANAGED_START) == 1
    assert second.count(MANAGED_END) == 1
    # Unrelated rules are preserved.
    assert "*.db" in second


def test_a_tracked_store_is_left_alone(repo):
    (repo / ".gitignore").write_text("", encoding="utf-8")
    assert _git(repo, "add", "--", ".tacit").returncode == 0

    status = ensure_store_tracked(repo)

    assert status["ignored"] is False
    assert status["tracked"] is True
    assert status["staged"] is False


def test_nested_store_paths_are_reincluded(repo):
    """`tacit move` can put the store under a subfolder that is also ignored."""
    moved = repo / "agent-memory" / ".tacit"
    moved.parent.mkdir()
    shutil.move(str(repo / ".tacit"), str(moved))
    (repo / ".gitignore").write_text("agent-memory/\n.tacit/\n", encoding="utf-8")

    status = ensure_store_tracked(repo, store_dir=moved)

    assert status["tracked"] is True
    assert _git(repo, "check-ignore", "-q", "agent-memory/.tacit/memory.db").returncode != 0
    ignore_text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "!agent-memory/" in ignore_text
    assert "!agent-memory/.tacit/" in ignore_text


def test_a_project_ignored_by_its_enclosing_repo_is_left_alone(tmp_path):
    """Test scratch dirs and vendored trees are excluded on purpose.

    The package itself lives inside a checkout, so an initialization inside an
    ignored subdirectory must not rewrite the enclosing repo's .gitignore or
    stage files into it.
    """
    outer = tmp_path / "outer"
    inner = outer / "scratch" / "project"
    (inner / ".tacit").mkdir(parents=True)
    (inner / ".tacit" / "memory.db").write_bytes(b"SQLite format 3\x00")
    (outer / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    assert _git(outer, "init").returncode == 0

    before = (outer / ".gitignore").read_text(encoding="utf-8")
    status = ensure_store_tracked(inner)

    assert status["git_repo"] is True
    assert status["tracked"] is False
    assert status["ignore_fixed"] is False
    assert (outer / ".gitignore").read_text(encoding="utf-8") == before
    assert _git(outer, "ls-files", "--", "scratch").stdout.strip() == ""


def test_git_toplevel_is_discovered_from_a_subdirectory(repo):
    subdir = repo / "src"
    subdir.mkdir()

    assert git_toplevel(subdir) == repo.resolve()


def test_managed_block_quotes_the_store_path():
    block = managed_block(".tacit")

    assert "!.tacit/" in block
    assert "!.tacit/**" in block
    assert ".tacit/models/" in block


def test_a_deep_filtered_then_reincluded_store_keeps_markdown(repo):
    # A nested rule that ignores everything first is a common template shape.
    (repo / ".gitignore").write_text("*\n!main.py\n!.gitignore\n", encoding="utf-8")

    status = ensure_store_tracked(repo)

    assert status["tracked"] is True
    assert "memory.db" in _git(repo, "ls-files", "--", ".tacit").stdout
