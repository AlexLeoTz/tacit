"""Self-update machinery for the Tacit CLI.

This module intentionally depends on nothing but the standard library so that it
can be imported by the detached Windows updater *while* the Tacit distribution
is being replaced.

Why this exists
---------------
On Windows a console script (``Scripts\\tacit.exe``) cannot be replaced while a
``tacit`` process is running; ``pip`` fails with::

    WARNING: Failed to write executable - trying to use .deleteme logic
    ERROR: Could not install packages due to an OSError: [WinError 32] ...
    'Scripts\\tacit.exe' -> 'Scripts\\tacit.exe.deleteme'

The fix has three parts, all implemented here:

1. **Stop everything that can hold the file.** ``taskkill /IM tacit.exe`` only
   kills the thin launcher; the real work runs in a child ``python.exe`` that
   makes up the ``tacit`` entry point (and in ``serve``/``mcp`` daemons spawned
   by editors). Those are enumerated and terminated too.
2. **Wait until the file is genuinely replaceable** instead of sleeping a fixed
   two seconds, then *quarantine* the old launcher by renaming it aside so
   ``pip`` writes a fresh one without a conflict.
3. **Make the result observable.** Everything is written to a log file and a
   JSON status file, because the updater runs detached and has no console.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_GIT_URL = "https://github.com/AlexLeoTz/tacit.git"

#: Console-script artefacts that pip may need to (re)write for the ``tacit`` entry point.
CONSOLE_SCRIPT_NAMES: Tuple[str, ...] = ("tacit.exe", "tacit-script.py", "tacit-script.pyw", "tacit")

#: How long to wait for the parent ``tacit`` process to disappear.
PARENT_EXIT_TIMEOUT = 60.0

#: How long to wait for ``tacit.exe`` to become replaceable before giving up.
REPLACE_TIMEOUT = 45.0


# ---------------------------------------------------------------------------
# Paths / environment
# ---------------------------------------------------------------------------

def real_python_executable() -> str:
    """Return an interpreter path that is safe to re-invoke.

    ``sys.executable`` is normally ``python.exe``, but if Tacit is ever launched
    through a wrapper that reports the wrapper as the executable we fall back to
    the base interpreter, because re-running the wrapper is what causes the
    self-lock in the first place.
    """
    exe = sys.executable or ""
    name = os.path.basename(exe).lower()
    if name.startswith("python"):
        return exe
    base = getattr(sys, "_base_executable", "") or ""
    if base and os.path.basename(base).lower().startswith("python"):
        return base
    candidate = Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python3")
    if candidate.exists():
        return str(candidate)
    return exe


def package_parent_dir() -> Path:
    """Directory that must be on ``sys.path`` to ``import src.utils.updater``."""
    return Path(__file__).resolve().parents[2]


def find_foreign_checkout(start: Optional[Path] = None) -> Optional[Path]:
    """Return a Tacit checkout near ``start`` that is *not* the one being executed.

    An editable install permanently pins the CLI to the directory it was
    installed from. Editing a different clone then appears to do nothing: the
    command keeps running the pinned copy. Detecting it turns a baffling
    "my changes have no effect" report into a one-line explanation.
    """
    try:
        candidate = Path(start or Path.cwd()).resolve()
    except OSError:
        return None
    running = package_parent_dir()
    for probe in (candidate, *list(candidate.parents)[:4]):
        is_checkout = (probe / "setup.py").exists() and (probe / "src" / "cli" / "main.py").exists()
        if not is_checkout:
            continue
        return None if probe == running else probe
    return None


def scripts_dir() -> Path:
    return Path(sysconfig.get_path("scripts") or "")


def purelib_dir() -> Path:
    return Path(sysconfig.get_path("purelib") or "")


def config_dir() -> Path:
    """Directory holding Tacit's global, per-user state (update cache/log/status)."""
    return Path.home() / ".gemini" / "config"


def update_log_path() -> Path:
    return config_dir() / "tacit_update.log"


def update_status_path() -> Path:
    return config_dir() / "tacit_update_status.json"


# ---------------------------------------------------------------------------
# pip leftovers
# ---------------------------------------------------------------------------

def _is_tacit_debris_name(name: str) -> bool:
    """True for the ``~acit-0.1.0.dist-info`` style directories pip leaves behind.

    A failed ``pip`` uninstall renames ``tacit-0.1.0.dist-info`` by replacing
    successive characters with ``~`` — hence ``~acit``, ``~-cit``, ``~=cit``,
    ``~~cit`` and finally ``~``. Only those are matched, so unrelated leftovers
    belonging to other packages are left alone.
    """
    if name == "~":
        return True
    if not name.startswith("~"):
        return False
    return "cit" in name.lower()


def find_tacit_debris(directories: Optional[Iterable[Path]] = None) -> List[Path]:
    """Return stale ``~*`` distribution directories and ``.deleteme`` files."""
    dirs = list(directories) if directories is not None else [purelib_dir(), scripts_dir()]
    found: List[Path] = []
    for directory in dirs:
        try:
            if not directory.is_dir():
                continue
            for entry in sorted(directory.iterdir()):
                if entry.is_dir() and _is_tacit_debris_name(entry.name):
                    found.append(entry)
                elif entry.is_file() and (
                    entry.name.endswith(".deleteme") or ".old-" in entry.name
                ):
                    found.append(entry)
        except OSError:
            continue
    return found


def clean_tacit_debris(directories: Optional[Iterable[Path]] = None) -> Tuple[List[str], List[str]]:
    """Delete stale pip leftovers. Returns ``(removed, failed)`` path strings."""
    removed: List[str] = []
    failed: List[str] = []
    for path in find_tacit_debris(directories):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))
        except OSError:
            failed.append(str(path))
    return removed, failed


# ---------------------------------------------------------------------------
# File-lock handling
# ---------------------------------------------------------------------------

def is_replaceable(path: Path) -> bool:
    """True when ``pip`` would be able to move ``path`` aside.

    Renaming a *running* executable is allowed by Windows; a rename only fails
    when another process holds the file open without ``FILE_SHARE_DELETE`` (the
    case that produces ``[WinError 32]``). A rename round-trip is therefore the
    exact question ``pip`` asks, so we ask it too.
    """
    if not path.exists():
        return True
    probe = path.with_name(path.name + ".lockprobe")
    try:
        path.rename(probe)
    except OSError:
        return False
    try:
        probe.rename(path)
    except OSError:
        # The file is free (the rename succeeded) but we could not restore it;
        # report it as replaceable and let the caller deal with the stray file.
        return True
    return True


def wait_for_replaceable(path: Path, timeout: float = REPLACE_TIMEOUT,
                         interval: float = 0.5) -> bool:
    """Poll :func:`is_replaceable` until it succeeds or ``timeout`` elapses."""
    deadline = time.time() + max(0.0, timeout)
    while True:
        if is_replaceable(path):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(interval)


def quarantine_console_scripts(tag: Optional[str] = None,
                               directory: Optional[Path] = None
                               ) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Rename the ``tacit`` launchers aside so ``pip`` can write fresh ones.

    Returns ``(moved, failed)`` where ``moved`` holds ``(original, quarantined)``
    pairs. A launcher that is still locked is reported in ``failed`` rather than
    raising, so the caller can decide whether to retry.
    """
    tag = tag or time.strftime("%Y%m%d%H%M%S")
    target_dir = directory or scripts_dir()
    moved: List[Tuple[str, str]] = []
    failed: List[str] = []
    for name in CONSOLE_SCRIPT_NAMES:
        candidate = target_dir / name
        if not candidate.exists():
            continue
        destination = candidate.with_name(candidate.name + f".old-{tag}")
        try:
            candidate.rename(destination)
            moved.append((str(candidate), str(destination)))
        except OSError:
            failed.append(str(candidate))
    return moved, failed


def remove_quarantined_files(directory: Optional[Path] = None) -> List[str]:
    """Best-effort removal of ``*.old-*`` launchers left by earlier updates."""
    target_dir = directory or scripts_dir()
    removed: List[str] = []
    try:
        if not target_dir.is_dir():
            return removed
        for entry in target_dir.iterdir():
            if entry.is_file() and ".old-" in entry.name and entry.name.startswith("tacit"):
                try:
                    entry.unlink()
                    removed.append(str(entry))
                except OSError:
                    pass
    except OSError:
        pass
    return removed


# ---------------------------------------------------------------------------
# Daemon termination
# ---------------------------------------------------------------------------

def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                capture_output=True, text=True, timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return str(int(pid)) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_for_pid_exit(pid: int, timeout: float = PARENT_EXIT_TIMEOUT,
                      interval: float = 0.25) -> bool:
    """Block until ``pid`` is gone. Returns True when it exited in time."""
    deadline = time.time() + max(0.0, timeout)
    while process_is_alive(pid):
        if time.time() >= deadline:
            return False
        time.sleep(interval)
    return True


#: Matches the ``python.exe`` child the console-script launcher spawns, and
#: ``python -m src.cli.main`` invocations used by editor MCP configuration.
_TACIT_PYTHON_PATTERN = r"(?:src[\\/]cli[\\/]main|Scripts[\\/]tacit\.exe|Scripts[\\/]tacit-script)"

_PWSH_ENUMERATE = (
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
    "Where-Object { $_.CommandLine -and $_.CommandLine -match $env:TACIT_PS_PATTERN } | "
    "Select-Object -ExpandProperty ProcessId"
)


def list_windows_tacit_python_pids() -> List[int]:
    """PIDs of ``python.exe`` processes that are running the Tacit entry point."""
    env = dict(os.environ)
    env["TACIT_PS_PATTERN"] = _TACIT_PYTHON_PATTERN
    for shell in ("powershell", "pwsh"):
        try:
            completed = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", _PWSH_ENUMERATE],
                capture_output=True, text=True, env=env, timeout=25,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        pids = []
        for token in completed.stdout.split():
            token = token.strip()
            if token.isdigit():
                pids.append(int(token))
        return pids
    return []


def terminate_windows_daemons(exclude_pids: Iterable[int] = ()) -> List[int]:
    """Stop every process that could keep ``tacit.exe`` open. Returns killed PIDs."""
    excluded = {int(pid) for pid in exclude_pids}
    killed: List[int] = []

    # ``/T`` is essential: it takes the child ``python.exe`` down with the launcher.
    subprocess.run(["taskkill", "/F", "/T", "/IM", "tacit.exe"],
                   capture_output=True, check=False)

    for pid in list_windows_tacit_python_pids():
        if pid in excluded:
            continue
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, check=False)
        killed.append(pid)
    return killed


#: Only background daemons — never a bare ``tacit <command>``, which would match
#: (and kill) the process running ``tacit update`` itself.
_UNIX_DAEMON_PATTERN = r"(?:tacit|src[./]cli[./]main).*(?:serve|dashboard|mcp)"


def terminate_unix_daemons(exclude_pids: Iterable[int] = ()) -> List[int]:
    """SIGTERM background ``tacit serve``/``dashboard``/``mcp`` daemons.

    The previous implementation ran ``pkill -f tacit``, which matches the command
    line of the very process running ``tacit update`` and killed itself.
    """
    excluded = {int(pid) for pid in exclude_pids}
    excluded.add(os.getpid())
    excluded.add(os.getppid())
    killed: List[int] = []
    try:
        completed = subprocess.run(["pgrep", "-f", _UNIX_DAEMON_PATTERN],
                                   capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return killed
    for token in completed.stdout.split():
        if not token.isdigit():
            continue
        pid = int(token)
        if pid in excluded or pid <= 0:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except OSError:
            continue
    return killed


# ---------------------------------------------------------------------------
# pip invocation
# ---------------------------------------------------------------------------

def build_pip_command(python_exe: str, target: str, editable: bool = False) -> List[str]:
    """Build the ``pip install`` command for a global or editable (source) update."""
    if editable:
        return [python_exe, "-m", "pip", "install", "--upgrade", "--no-deps", "-e", target]
    return [
        python_exe, "-m", "pip", "install",
        "--upgrade", "--force-reinstall", "--no-cache-dir", "--no-deps", target,
    ]


def installed_version(python_exe: Optional[str] = None) -> Optional[str]:
    """Read the installed Tacit version in a fresh interpreter (avoids stale caches)."""
    exe = python_exe or real_python_executable()
    try:
        completed = subprocess.run(
            [exe, "-c", "import importlib.metadata as m; print(m.version('tacit'))"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


# ---------------------------------------------------------------------------
# Shared install sequence
# ---------------------------------------------------------------------------

def _default_logger(message: str) -> None:  # pragma: no cover - trivial
    print(message, flush=True)


def perform_update(spec: Dict[str, Any],
                   log: Callable[[str], None] = _default_logger) -> Dict[str, Any]:
    """Run ``git pull`` (dev mode), ``pip install`` and the rules refresh.

    Used both by the Unix in-process path and by the detached Windows runner, so
    the two platforms cannot drift apart again.
    """
    python_exe = spec.get("python") or real_python_executable()
    editable = bool(spec.get("editable"))
    attempts = int(spec.get("attempts", 3))
    source_root = spec.get("source_root")
    # An editable update always targets the checkout it was installed from, so a
    # stale `target` in the spec can never redirect it at the Git URL.
    if editable and source_root:
        target = str(source_root)
    else:
        target = spec.get("target") or f"git+{spec.get('git_url') or DEFAULT_GIT_URL}"
    result: Dict[str, Any] = {"ok": False, "mode": "editable" if editable else "global"}

    if editable and source_root:
        log(f"Pulling latest source in {source_root} ...")
        try:
            pull = subprocess.run(["git", "pull", "--ff-only"], cwd=source_root,
                                  capture_output=True, text=True, timeout=300)
            if pull.returncode != 0:
                log(f"git pull failed (continuing with local checkout): {pull.stderr.strip()}")
            else:
                log(pull.stdout.strip() or "Already up to date.")
        except (OSError, subprocess.SubprocessError) as exc:
            log(f"git pull unavailable ({exc}); continuing with local checkout.")

    command = build_pip_command(python_exe, target, editable=editable)
    log("Running: " + " ".join(command))

    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode == 0:
            log(f"pip install succeeded on attempt {attempt}.")
            result["ok"] = True
            break
        last_error = (completed.stderr or completed.stdout or "").strip()
        log(f"pip install attempt {attempt} failed:\n{last_error}")

        if not editable:
            log("Retrying with --user ...")
            user_command = command[:-1] + ["--user", command[-1]]
            user_attempt = subprocess.run(user_command, capture_output=True, text=True)
            if user_attempt.returncode == 0:
                log("pip install --user succeeded.")
                result["ok"] = True
                break
            last_error = (user_attempt.stderr or user_attempt.stdout or "").strip()
            log(f"--user retry failed:\n{last_error}")

        if attempt < attempts:
            time.sleep(2.0 * attempt)

    result["error"] = last_error
    result["version"] = installed_version(python_exe)
    if result["ok"]:
        log(f"Installed version: {result['version']}")

    if result["ok"] and spec.get("reinit"):
        cwd = spec.get("cwd")
        log("Refreshing workspace agent rules ...")
        refreshed = False
        for command in ([python_exe, "-m", "src.cli.main", "init", "--force"],
                        ["tacit", "init", "--force"]):
            try:
                done = subprocess.run(command, cwd=cwd, capture_output=True,
                                      text=True, timeout=180)
            except (OSError, subprocess.SubprocessError):
                continue
            if done.returncode == 0:
                refreshed = True
                break
        result["rules_refreshed"] = refreshed

    return result


# ---------------------------------------------------------------------------
# Windows detached runner
# ---------------------------------------------------------------------------

_RUNNER_TEMPLATE = '''\
"""Detached Tacit updater (auto-generated). Safe to delete."""
import json
import sys
from pathlib import Path

spec_path = Path(sys.argv[1])
spec = json.loads(spec_path.read_text(encoding="utf-8"))
sys.path.insert(0, spec["package_parent"])

from src.utils.updater import run_windows_update

raise SystemExit(run_windows_update(spec))
'''


def write_runner(directory: Optional[Path] = None) -> Path:
    """Write the small bootstrap script the detached interpreter executes."""
    target_dir = directory or config_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    runner = target_dir / "tacit_update_runner.py"
    runner.write_text(_RUNNER_TEMPLATE, encoding="utf-8")
    return runner


def write_status(status: Dict[str, Any], path: Optional[Path] = None) -> None:
    target = path or update_status_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(status)
        payload["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def read_status(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    target = path or update_status_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_log_tail(lines: int = 12, path: Optional[Path] = None) -> str:
    target = path or update_log_path()
    try:
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def launch_detached_windows_updater(spec: Dict[str, Any]) -> Path:
    """Start the updater in a detached process and return the runner path."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    runner = write_runner(directory)
    spec_path = directory / "tacit_update_spec.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        [spec["python"], str(runner), str(spec_path)],
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return runner


def run_windows_update(spec: Dict[str, Any]) -> int:
    """Entry point of the detached updater. Always writes a status file."""
    log_path = Path(spec.get("log") or update_log_path())
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:  # pragma: no cover - last-resort fallback
        log_file = open(os.devnull, "w", encoding="utf-8")

    started = time.time()

    def log(message: str) -> None:
        log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        log_file.flush()

    status: Dict[str, Any] = {
        "ok": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "editable" if spec.get("editable") else "global",
        "target": spec.get("target"),
    }
    try:
        log("=" * 60)
        log("Tacit updater started.")
        parent_pid = int(spec.get("parent_pid") or 0)
        if parent_pid:
            if not wait_for_pid_exit(parent_pid):
                log(f"Parent process {parent_pid} is still running; continuing anyway.")
            else:
                log(f"Parent process {parent_pid} exited.")

        killed = terminate_windows_daemons(exclude_pids={os.getpid()})
        if killed:
            log(f"Stopped Tacit python daemons: {killed}")
        status["daemons_stopped"] = killed

        target_exe = scripts_dir() / "tacit.exe"
        deadline = time.time() + REPLACE_TIMEOUT
        while not is_replaceable(target_exe) and time.time() < deadline:
            terminate_windows_daemons(exclude_pids={os.getpid()})
            time.sleep(1.0)
        status["launcher_replaceable"] = is_replaceable(target_exe)
        if not status["launcher_replaceable"]:
            log("WARNING: tacit.exe is still locked by another process; "
                "pip may not be able to replace it.")

        moved, failed = quarantine_console_scripts()
        if moved:
            log(f"Quarantined old launchers: {[dst for _, dst in moved]}")
        if failed:
            log(f"WARNING: could not move locked launchers: {failed}")
        status["quarantined"] = [dst for _, dst in moved]

        removed, not_removed = clean_tacit_debris()
        if removed:
            log(f"Removed stale pip leftovers: {removed}")
        if not_removed:
            log(f"Leftover cleanup deferred (in use): {not_removed}")
        status["debris_removed"] = removed

        result = perform_update(spec, log)
        status.update(result)
    except Exception as exc:  # pragma: no cover - defensive
        log(f"Updater crashed: {exc!r}")
        status["ok"] = False
        status["error"] = repr(exc)
    finally:
        status["duration_seconds"] = round(time.time() - started, 1)
        leftovers = remove_quarantined_files()
        if leftovers:
            log(f"Removed quarantined launchers: {leftovers}")
        log(f"Finished (ok={status.get('ok')}, version={status.get('version')}).")
        write_status(status, Path(spec.get("status") or update_status_path()))
        log_file.close()
    return 0 if status.get("ok") else 1
