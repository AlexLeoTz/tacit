"""No test may write outside this workspace.

Tacit keeps per-machine state outside any project: the cross-project registry
under ``~/.gemini/config`` and the update cache/log/status beside it. Running the
suite without isolation therefore registers every temporary mock project on the
developer's machine and rewrites their update status — silently, because
``register_project`` swallows write errors and stale registry entries are filtered
out on read.

These tests pin that guarantee down, so a future change that reintroduces a
hard-coded ``Path.home()`` fails here instead of quietly polluting a real machine.
"""

import json
import shutil
from pathlib import Path

import pytest

from src.utils import updater
from src.utils.config import Config, tacit_home


@pytest.fixture
def mock_project():
    """A throwaway project inside the workspace, never a real one."""
    base = Path(__file__).resolve().parent / "_isolation_tmp" / "mock-project"
    (base / "src").mkdir(parents=True, exist_ok=True)
    (base / ".git").mkdir(exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base.parent, ignore_errors=True)


def test_global_state_resolves_inside_the_workspace():
    workspace = Path(__file__).resolve().parent.parent

    assert workspace in Config.REGISTRY_FILE.parents
    assert workspace in tacit_home().parents
    assert workspace in updater.config_dir().parents


def test_registering_a_project_writes_only_inside_the_workspace(mock_project):
    Config.register_project(mock_project)

    assert Config.REGISTRY_FILE.exists()
    registered = json.loads(Config.REGISTRY_FILE.read_text(encoding="utf-8"))
    assert registered == {"mock-project": str(mock_project.resolve())}


def test_the_real_user_registry_is_never_the_target():
    """`~/.gemini/config` must not be where a test run points."""
    real_home = Path.home() / ".gemini" / "config"

    assert Config.REGISTRY_FILE.parent != real_home
    assert updater.config_dir() != real_home
    assert updater.update_log_path().parent != real_home


def test_updater_state_follows_tacit_home(monkeypatch):
    custom = Path(__file__).resolve().parent / "_isolation_tmp" / "custom-home"
    monkeypatch.setenv("TACIT_HOME", str(custom))

    assert updater.config_dir() == custom
    assert updater.update_log_path() == custom / "tacit_update.log"
