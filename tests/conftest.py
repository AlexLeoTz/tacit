"""Suite-wide isolation: no test may touch state outside this workspace.

Tacit keeps per-machine state outside any project — the cross-project registry
and the update cache/log/status under ``~/.gemini/config``. Without isolation,
running the tests registers every temporary mock project in the developer's real
registry, and the CLI's start-of-command hooks rewrite the real update-status
file. Both are silent: `register_project` swallows write errors, and a registry
entry pointing at a directory that no longer exists is filtered out on read, so
the damage is invisible until it accumulates.

Two independent layers guard against that:

1. ``TACIT_HOME`` is set at import time to a scratch directory *inside the
   workspace*, so ``Config.REGISTRY_FILE`` and ``updater.config_dir()`` resolve
   there even for code paths that never see the fixture below.
2. An autouse fixture re-points both explicitly for every test, which also covers
   tests that monkeypatch the registry themselves.
"""

import os
import re
import shutil
from pathlib import Path

import pytest

#: Everything Tacit considers "global, per-user state" lands here during a test
#: run. Set before `src.*` is imported, because `Config.REGISTRY_FILE` is computed
#: at import time.
_TACIT_HOME = Path(__file__).resolve().parent / "_tacit_home"
os.environ["TACIT_HOME"] = str(_TACIT_HOME)


@pytest.fixture
def tmp_path(request):
    """A throwaway directory inside the workspace, replacing pytest's `tmp_path`.

    pytest's own `tmp_path` lives in the OS temp directory. Under a sandbox that
    denies chmod/rmtree there (DSH's `%TEMP%\\dsh-*`), twenty-five tests failed or
    errored **from the fixture alone**, before a single assertion ran, which made a
    real regression indistinguishable from environment noise. A workspace-local
    mock project is writable everywhere, cannot leak state onto a developer's
    machine, and — because `tests/_scratch` carries its own `.git` marker — cannot
    be mistaken for this repository either.
    """
    from support import workspace_tempdir

    safe_name = re.sub(r"[^\w.-]+", "_", request.node.name)[:60] or "test"
    with workspace_tempdir(f"pytest-{safe_name}") as base:
        yield base


@pytest.fixture(autouse=True)
def no_writes_outside_the_workspace():
    """Fail the *test* that writes to the developer's real Tacit state.

    The isolation fixtures above redirect Tacit's per-machine state into the
    workspace, but a test can still leak: by patching the redirect away, by
    spawning a subprocess that rebuilds its environment, or by resolving the
    current repository instead of its own mock project. When that happened here,
    the only trace was a changed timestamp on a file nobody was looking at —
    weeks of accumulated junk registry entries in the worst case.

    Only the cross-project registry is checked, and only its mtime/size, so a
    concurrently running `tacit` command cannot be confused with a test write.
    """
    real_registry = Path.home() / ".gemini" / "config" / "tacit_projects.json"
    # The repository's own store is tracked in git; a test that opens it changes a
    # committed file. `tests/_scratch/.git` is what keeps implicit discovery from
    # walking up into it.
    repo_store = Path(__file__).resolve().parent.parent / ".tacit" / "memory.db"

    def snapshot(path):
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    before = (snapshot(real_registry), snapshot(repo_store))
    yield
    after = (snapshot(real_registry), snapshot(repo_store))

    if before[0] != after[0]:
        pytest.fail(
            f"this test modified the real project registry at {real_registry}.\n"
            "Tests must build their own mock project under tests/_scratch and let "
            "conftest redirect Config.REGISTRY_FILE; never write to the developer's "
            "~/.gemini/config."
        )
    if before[1] != after[1]:
        pytest.fail(
            f"this test modified this repository's own store at {repo_store}.\n"
            "Every test must operate on a mock project under tests/_scratch (which "
            "carries a .git marker so project discovery stops there)."
        )


@pytest.fixture(autouse=True)
def isolated_tacit_home(monkeypatch):
    """Point the registry and updater state at a workspace-local scratch dir."""
    local_home = _TACIT_HOME
    shutil.rmtree(local_home, ignore_errors=True)
    local_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TACIT_HOME", str(local_home))

    from src.utils.config import Config

    # `Config.REGISTRY_FILE` is computed at import time, so the environment alone
    # is not enough; `updater.config_dir()` re-reads TACIT_HOME on every call and
    # needs no patch — which `tests/test_isolation.py` relies on to prove it.
    monkeypatch.setattr(Config, "REGISTRY_FILE", local_home / "tacit_projects.json")

    yield

    # Never leave scratch state behind for the next run to inherit.
    shutil.rmtree(local_home, ignore_errors=True)
