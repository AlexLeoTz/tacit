"""Tests for the Tacit self-update machinery and the ``tacit update`` command.

These cover the Windows ``[WinError 32]`` regression: the updater must stop the
process that holds ``Scripts\\tacit.exe`` open, wait until the launcher is
genuinely replaceable, quarantine the old launcher, and leave an inspectable log
and status file behind instead of failing silently in a detached process.
"""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.utils import updater


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    import shutil

    base = Path(__file__).resolve().parent / "_updater_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# pip leftovers
# ---------------------------------------------------------------------------

#: The exact debris observed in site-packages after the failed update.
OBSERVED_DEBRIS = [
    "~",
    "~-cit-0.1.0.dist-info",
    "~.cit-0.1.0.dist-info",
    "~=cit-0.1.0.dist-info",
    "~acit-0.1.0.dist-info",
    "~~cit-0.1.0.dist-info",
]


@pytest.mark.parametrize("name", OBSERVED_DEBRIS)
def test_is_tacit_debris_name_matches_pip_leftovers(name):
    assert updater._is_tacit_debris_name(name) is True


@pytest.mark.parametrize("name", ["~rc", "numpy", "tacit-0.1.0.dist-info", "~foo"])
def test_is_tacit_debris_name_ignores_unrelated_entries(name):
    assert updater._is_tacit_debris_name(name) is False


def test_clean_tacit_debris_removes_only_tacit_leftovers(tmp_dir):
    for name in OBSERVED_DEBRIS + ["tacit-0.1.0.dist-info", "~rc", "other-package"]:
        (tmp_dir / name).mkdir()

    removed, failed = updater.clean_tacit_debris([tmp_dir])

    assert failed == []
    assert {Path(p).name for p in removed} == set(OBSERVED_DEBRIS)
    remaining = {entry.name for entry in tmp_dir.iterdir()}
    assert remaining == {"tacit-0.1.0.dist-info", "~rc", "other-package"}


def test_find_tacit_debris_reports_deleteme_files(tmp_dir):
    (tmp_dir / "tacit.exe.deleteme").write_text("stale", encoding="utf-8")
    (tmp_dir / "tacit.exe.old-20240101000000").write_text("stale", encoding="utf-8")
    (tmp_dir / "unrelated.exe").write_text("keep", encoding="utf-8")

    found = {p.name for p in updater.find_tacit_debris([tmp_dir])}

    assert found == {"tacit.exe.deleteme", "tacit.exe.old-20240101000000"}


# ---------------------------------------------------------------------------
# Lock handling
# ---------------------------------------------------------------------------

def test_is_replaceable_true_for_missing_file(tmp_dir):
    assert updater.is_replaceable(tmp_dir / "does-not-exist.exe") is True


def test_is_replaceable_true_for_plain_file(tmp_dir):
    target = tmp_dir / "tacit.exe"
    target.write_text("launcher", encoding="utf-8")
    assert updater.is_replaceable(target) is True
    assert target.exists(), "the probe must restore the file it renamed"


@pytest.mark.skipif(os.name != "nt", reason="Windows-only file-locking semantics")
def test_is_replaceable_false_while_handle_is_open(tmp_dir):
    target = tmp_dir / "tacit.exe"
    target.write_text("launcher", encoding="utf-8")

    handle = open(target, "rb")  # no FILE_SHARE_DELETE -> pip's .deleteme rename fails
    try:
        assert updater.is_replaceable(target) is False
    finally:
        handle.close()

    assert updater.is_replaceable(target) is True


def test_wait_for_replaceable_times_out(monkeypatch):
    monkeypatch.setattr(updater, "is_replaceable", lambda path: False)
    assert updater.wait_for_replaceable(Path("whatever.exe"), timeout=0.05, interval=0.01) is False


def test_quarantine_console_scripts_moves_launchers(tmp_dir):
    for name in updater.CONSOLE_SCRIPT_NAMES:
        (tmp_dir / name).write_text("launcher", encoding="utf-8")

    moved, failed = updater.quarantine_console_scripts(tag="TESTTAG", directory=tmp_dir)

    assert failed == []
    assert len(moved) == len(updater.CONSOLE_SCRIPT_NAMES)
    for original, quarantined in moved:
        assert not Path(original).exists()
        assert Path(quarantined).name.endswith(".old-TESTTAG")


def test_remove_quarantined_files_cleans_previous_updates(tmp_dir):
    stale = tmp_dir / "tacit.exe.old-20240101000000"
    stale.write_text("old", encoding="utf-8")
    (tmp_dir / "tacit.exe").write_text("current", encoding="utf-8")

    removed = updater.remove_quarantined_files(tmp_dir)

    assert removed == [str(stale)]
    assert (tmp_dir / "tacit.exe").exists()


# ---------------------------------------------------------------------------
# Daemon termination
# ---------------------------------------------------------------------------

class _Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_terminate_unix_daemons_never_kills_itself(monkeypatch):
    """Regression: the old code ran `pkill -f tacit`, which matched the very
    process running `tacit update` and killed it mid-update."""
    own_pid = os.getpid()
    parent_pid = os.getppid()
    victim = own_pid + 100000

    monkeypatch.setattr(
        updater.subprocess, "run",
        lambda *a, **k: _Completed(stdout=f"{own_pid}\n{parent_pid}\n{victim}\n"),
    )
    signalled = []
    monkeypatch.setattr(updater.os, "kill", lambda pid, sig: signalled.append(pid))

    killed = updater.terminate_unix_daemons()

    assert killed == [victim]
    assert own_pid not in signalled
    assert parent_pid not in signalled


def test_terminate_unix_daemons_pattern_excludes_foreground_commands():
    # `tacit update` / `tacit init` must not match; only background daemons should.
    import re

    assert re.search(updater._UNIX_DAEMON_PATTERN, "/usr/bin/tacit mcp")
    assert re.search(updater._UNIX_DAEMON_PATTERN, "python -m src.cli.main serve")
    assert not re.search(updater._UNIX_DAEMON_PATTERN, "/usr/bin/tacit update")


def test_list_windows_tacit_python_pids_parses_shell_output(monkeypatch):
    monkeypatch.setattr(
        updater.subprocess, "run",
        lambda *a, **k: _Completed(stdout="1234\r\n5678\r\n"),
    )
    assert updater.list_windows_tacit_python_pids() == [1234, 5678]


def test_terminate_windows_daemons_tree_kills_and_excludes(monkeypatch):
    commands = []
    monkeypatch.setattr(updater, "list_windows_tacit_python_pids", lambda: [4321, 999])
    monkeypatch.setattr(
        updater.subprocess, "run",
        lambda cmd, **k: commands.append(cmd) or _Completed(),
    )

    killed = updater.terminate_windows_daemons(exclude_pids={999})

    assert killed == [4321]
    assert ["taskkill", "/F", "/T", "/IM", "tacit.exe"] in commands
    assert ["taskkill", "/F", "/T", "/PID", "4321"] in commands
    assert ["taskkill", "/F", "/T", "/PID", "999"] not in commands


# ---------------------------------------------------------------------------
# pip invocation / install sequence
# ---------------------------------------------------------------------------

def test_build_pip_command_global_install():
    command = updater.build_pip_command("python.exe", "git+https://example.com/tacit.git")
    assert command[:3] == ["python.exe", "-m", "pip"]
    assert "--force-reinstall" in command
    assert "-e" not in command
    assert command[-1] == "git+https://example.com/tacit.git"


def test_build_pip_command_editable_install():
    command = updater.build_pip_command("python.exe", r"D:\src\tacit", editable=True)
    assert command[-2:] == ["-e", r"D:\src\tacit"]
    assert "--force-reinstall" not in command


def _fake_run_factory(calls, pip_failures=0):
    state = {"pip": 0}

    def fake_run(command, **kwargs):
        calls.append(command)
        joined = " ".join(str(part) for part in command)
        if "pip" in joined and "install" in joined:
            state["pip"] += 1
            if state["pip"] <= pip_failures:
                return _Completed(returncode=1, stderr="ERROR: WinError 32")
            return _Completed(returncode=0, stdout="Successfully installed tacit")
        if "importlib.metadata" in joined:
            return _Completed(returncode=0, stdout="0.1.0\n")
        return _Completed(returncode=0)

    return fake_run


def test_perform_update_retries_after_winerror32(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "run", _fake_run_factory(calls, pip_failures=1))
    monkeypatch.setattr(updater.time, "sleep", lambda seconds: None)

    result = updater.perform_update(
        {"python": "python.exe", "git_url": "https://example.com/tacit.git",
         "target": "git+https://example.com/tacit.git", "attempts": 3, "reinit": False},
        log=lambda message: None,
    )

    assert result["ok"] is True
    assert result["version"] == "0.1.0"
    pip_attempts = [c for c in calls if "install" in " ".join(str(p) for p in c)]
    assert len(pip_attempts) == 2


def test_perform_update_editable_runs_git_pull(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "run", _fake_run_factory(calls))

    result = updater.perform_update(
        {"python": "python.exe", "editable": True, "source_root": "/src/tacit",
         "reinit": False, "attempts": 1},
        log=lambda message: None,
    )

    assert result["ok"] is True
    assert any(c[:3] == ["git", "pull", "--ff-only"] for c in calls)
    pip = [c for c in calls if "install" in " ".join(str(p) for p in c)][0]
    assert "-e" in pip and "/src/tacit" in pip


def test_perform_update_reports_failure(monkeypatch):
    monkeypatch.setattr(updater.subprocess, "run", _fake_run_factory([], pip_failures=99))
    monkeypatch.setattr(updater.time, "sleep", lambda seconds: None)

    result = updater.perform_update(
        {"python": "python.exe", "target": "git+https://example.com/tacit.git",
         "attempts": 2, "reinit": False},
        log=lambda message: None,
    )

    assert result["ok"] is False
    assert "WinError 32" in result["error"]


# ---------------------------------------------------------------------------
# Detached Windows runner
# ---------------------------------------------------------------------------

def _patch_windows_runner(monkeypatch, tmp_dir, install_ok=True):
    status_file = tmp_dir / "status.json"
    monkeypatch.setattr(updater, "wait_for_pid_exit", lambda pid, timeout=None: True)
    monkeypatch.setattr(updater, "terminate_windows_daemons", lambda exclude_pids=(): [])
    monkeypatch.setattr(updater, "is_replaceable", lambda path: True)
    monkeypatch.setattr(updater, "quarantine_console_scripts", lambda *a, **k: ([], []))
    monkeypatch.setattr(updater, "clean_tacit_debris", lambda *a, **k: ([], []))
    monkeypatch.setattr(updater, "remove_quarantined_files", lambda *a, **k: [])
    monkeypatch.setattr(
        updater, "perform_update",
        lambda spec, log=None: {"ok": install_ok, "version": "0.1.0", "error": "" if install_ok else "boom"},
    )
    return status_file


def test_run_windows_update_writes_status_file(monkeypatch, tmp_dir):
    status_file = _patch_windows_runner(monkeypatch, tmp_dir, install_ok=True)
    spec = {"parent_pid": 1234, "python": "python.exe", "target": "git+https://x/t.git",
            "log": str(tmp_dir / "update.log"), "status": str(status_file)}

    assert updater.run_windows_update(spec) == 0

    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["version"] == "0.1.0"
    assert "Tacit updater started." in (tmp_dir / "update.log").read_text(encoding="utf-8")


def test_run_windows_update_records_failure(monkeypatch, tmp_dir):
    status_file = _patch_windows_runner(monkeypatch, tmp_dir, install_ok=False)
    spec = {"parent_pid": 1234, "python": "python.exe", "target": "git+https://x/t.git",
            "log": str(tmp_dir / "update.log"), "status": str(status_file)}

    assert updater.run_windows_update(spec) == 1

    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["ok"] is False
    assert status["error"] == "boom"


def test_write_runner_script_is_importable(tmp_dir):
    runner = updater.write_runner(tmp_dir)
    content = runner.read_text(encoding="utf-8")
    assert "run_windows_update" in content
    assert "package_parent" in content


# ---------------------------------------------------------------------------
# Stale / foreign checkout detection
# ---------------------------------------------------------------------------

def _make_checkout(root):
    (root / "src" / "cli").mkdir(parents=True)
    (root / "setup.py").write_text("# marker", encoding="utf-8")
    (root / "src" / "cli" / "main.py").write_text("# marker", encoding="utf-8")
    return root


def test_find_foreign_checkout_detects_other_clone(tmp_dir, monkeypatch):
    """Regression: an editable install pins the CLI to the directory it was
    installed from, so a different checkout silently has no effect."""
    running = _make_checkout(tmp_dir / "running-clone")
    other = _make_checkout(tmp_dir / "other-clone")
    monkeypatch.setattr(updater, "package_parent_dir", lambda: running)

    assert updater.find_foreign_checkout(other) == other


def test_find_foreign_checkout_ignores_the_running_checkout(tmp_dir, monkeypatch):
    running = _make_checkout(tmp_dir / "running-clone")
    monkeypatch.setattr(updater, "package_parent_dir", lambda: running)

    assert updater.find_foreign_checkout(running) is None
    assert updater.find_foreign_checkout(running / "src") is None


def test_find_foreign_checkout_walks_up_to_enclosing_checkout(tmp_dir, monkeypatch):
    """A nested working directory resolves to the checkout that encloses it."""
    running = _make_checkout(tmp_dir / "running-clone")
    monkeypatch.setattr(updater, "package_parent_dir", lambda: running)
    repo_root = Path(__file__).resolve().parents[1]

    assert updater.find_foreign_checkout(tmp_dir) == repo_root
    assert updater.find_foreign_checkout(repo_root) is None or repo_root != running


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_version_flag_is_available(monkeypatch):
    """`tacit update` and the docs tell users to verify with `tacit --version`,
    which did not exist before."""
    from src import __version__

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout
    # The code location is printed too: an editable install pins the CLI to the
    # directory it was installed from, which is the fastest way to spot a stale one.
    assert str(updater.package_parent_dir()) in result.stdout.replace("\n", " ")


def test_update_launches_detached_updater_on_windows(monkeypatch, tmp_dir):
    import platform

    captured = {}

    def fake_launch(spec):
        captured.update(spec)
        return tmp_dir / "runner.py"

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(updater, "launch_detached_windows_updater", fake_launch)
    monkeypatch.setattr(updater, "read_status", lambda path=None: None)
    monkeypatch.setattr(updater, "update_log_path", lambda: tmp_dir / "update.log")

    result = CliRunner().invoke(app, ["update"])

    assert result.exit_code == 0
    assert captured["parent_pid"] == os.getpid()
    assert captured["python"] == updater.real_python_executable()
    assert captured["package_parent"] == str(updater.package_parent_dir())
    assert captured["cwd"] == str(Path.cwd())
    assert "update started in the background" in result.stdout


def test_update_warns_about_previous_failed_run(monkeypatch, tmp_dir):
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(updater, "launch_detached_windows_updater", lambda spec: tmp_dir / "r.py")
    monkeypatch.setattr(
        updater, "read_status",
        lambda path=None: {"ok": False, "error": "ERROR: [WinError 32] tacit.exe", "target": "git+x"},
    )
    monkeypatch.setattr(updater, "update_log_path", lambda: tmp_dir / "update.log")

    result = CliRunner().invoke(app, ["update"])

    assert result.exit_code == 0
    assert "previous update did not finish cleanly" in result.stdout
    assert "WinError 32" in result.stdout


def test_update_uses_editable_mode_for_source_checkout(monkeypatch, tmp_dir):
    import platform

    captured = {}
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(updater, "launch_detached_windows_updater",
                        lambda spec: captured.update(spec) or (tmp_dir / "r.py"))
    monkeypatch.setattr(updater, "read_status", lambda path=None: None)
    monkeypatch.setattr(updater, "update_log_path", lambda: tmp_dir / "update.log")
    monkeypatch.setattr("src.cli.main._resolve_update_mode", lambda force: (True, Path("/src/tacit")))

    result = CliRunner().invoke(app, ["update"])

    assert result.exit_code == 0
    assert captured["editable"] is True
    assert captured["source_root"] == str(Path("/src/tacit"))
    assert captured["target"] == str(Path("/src/tacit"))
