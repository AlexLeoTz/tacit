"""Make the project's ``.tacit`` store travel with the repository.

A Tacit store is the project's institutional memory: the decisions, hacks,
constraints and resolved errors that a fresh clone needs in order to give an
agent the same context it had on the machine where the work happened. If
``.tacit`` is ignored — by a template ``.gitignore`` that ignores dot-directories,
by ``*.db``, or by a hand-written ``.tacit/`` rule — the code arrives on the new
machine and every memory is silently missing. That failure is invisible until
somebody asks "why did we do it this way?" and Tacit answers "nothing found".

So initialization and MCP startup call :func:`ensure_store_tracked`:

1. discover the enclosing git work tree (no-op when the project is not a repo);
2. append a managed ``.gitignore`` block that re-includes the store and its data
   files, while keeping the regenerable embedding cache and SQLite WAL files out;
3. stage the store once (``git add``), without committing, when it was previously
   ignored.

The block is idempotent and is replaced rather than duplicated, so a store moved
with ``tacit move`` gets fresh paths on the next run. Tacit never rewrites the
user's unrelated ignore rules and never commits anything on their behalf.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MANAGED_START = "# >>> tacit memory store (managed by Tacit; keep it tracked) >>>"
MANAGED_END = "# <<< tacit memory store (managed by Tacit) <<<"

#: Files that carry knowledge. Everything else under the store is either
#: regenerable (the embedding cache) or SQLite runtime state.
_DATA_FILES = (
    "memory.db",
    "config.json",
    "project-tree.json",
    "file-table.json",
    "gists.json",
    "location",
)

#: Regenerable or actively dangerous to commit. These rules come *after* the
#: re-include patterns, because the last matching rule wins in gitignore.
_RUNTIME_IGNORES = (
    "models/",
    "_*/",
    "memory.db-wal",
    "memory.db-shm",
    "memory.db-journal",
    "*.pyc",
    "__pycache__/",
)

#: (repo, store) pairs already ensured in this process. Startup is the only
#: caller, but an MCP client can construct several servers per session.
_ENSURED: dict[tuple[str, str], Dict[str, Any]] = {}

BlockInfo = Dict[str, Any]


def _git(cwd: str | Path, *args: str) -> Optional[subprocess.CompletedProcess]:
    """Run a git command without ever letting it break the caller."""
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def git_toplevel(project_root: str | Path) -> Optional[Path]:
    """Return the enclosing work-tree root, or ``None`` when this is not a repo."""
    if not shutil.which("git"):
        return None
    proc = _git(project_root, "rev-parse", "--show-toplevel")
    if proc is None or proc.returncode != 0:
        return None
    raw = proc.stdout.strip().splitlines()
    if not raw:
        return None
    try:
        return Path(raw[-1]).resolve()
    except (OSError, RuntimeError):
        return None


def _relative_to_repo(store_dir: str | Path, toplevel: Path) -> Optional[str]:
    """Store path relative to the repo root, gitignore-formatted (forward slashes)."""
    try:
        rel = Path(store_dir).resolve().relative_to(toplevel)
    except (OSError, RuntimeError, ValueError):
        return None
    text = rel.as_posix()
    return "" if text == "." else text


def _ignore_escape(path: str) -> str:
    """Escape gitignore metacharacters so a path is matched literally.

    A directory named ``project[1]`` would otherwise be read as a character
    class, and a leading ``!`` or ``#`` as syntax rather than part of the name.
    """
    escaped = path
    for char in ("\\", "*", "?", "[", "]"):
        escaped = escaped.replace(char, "\\" + char)
    if escaped.startswith(("!", "#")):
        escaped = "\\" + escaped
    return escaped


def managed_block(store_rel: str) -> str:
    """The managed .gitignore block for one store location."""
    parts = [part for part in store_rel.split("/") if part and part != "."]
    store = "/".join(parts)
    if not store:
        return ""

    lines = [
        MANAGED_START,
        "# The .tacit store is this project's institutional memory. If git ignores",
        "# it, a fresh clone loses every recorded decision. Do not add an ignore",
        "# rule for the store itself; only the regenerable cache below stays out.",
    ]
    # Re-include each ancestor, then the store and its contents. Git cannot
    # re-include a file while one of its parent directories is excluded.
    prefix = ""
    for part in parts[:-1]:
        prefix = f"{prefix}/{part}" if prefix else part
        lines.append(f"!{_ignore_escape(prefix)}/")
    lines.append(f"!{_ignore_escape(store)}/")
    lines.append(f"!{_ignore_escape(store)}/**")
    for pattern in _RUNTIME_IGNORES:
        lines.append(f"{store}/{pattern}")
    lines.append(MANAGED_END)
    return "\n".join(lines)


def _strip_managed_block(text: str) -> str:
    """Remove every managed block, including duplicates left by older runs."""
    while True:
        start = text.find(MANAGED_START)
        if start == -1:
            return text
        end = text.find(MANAGED_END, start)
        if end == -1:
            # A truncated block: drop everything from the marker onward.
            return text[:start].rstrip() + ("\n" if text[:start].strip() else "")
        end += len(MANAGED_END)
        while end < len(text) and text[end] in "\r\n":
            end += 1
        text = text[:start] + text[end:]


def _write_managed_block(gitignore: Path, store_rel: str) -> bool:
    """Insert/replace the managed block. Returns True when the file changed."""
    block = managed_block(store_rel)
    if not block:
        return False

    try:
        original = gitignore.read_text(encoding="utf-8", errors="replace")
    except OSError:
        original = ""

    cleaned = _strip_managed_block(original).rstrip()
    body = (cleaned + "\n\n" if cleaned else "") + block + "\n"

    if body == original:
        return False
    try:
        gitignore.parent.mkdir(parents=True, exist_ok=True)
        gitignore.write_text(body, encoding="utf-8")
        return True
    except OSError:
        return False


def _path_ignored(toplevel: Path, path: str) -> bool:
    proc = _git(toplevel, "check-ignore", "-q", "--no-index", "--", path)
    return proc is not None and proc.returncode == 0


def _is_ignored(toplevel: Path, store_rel: str) -> bool:
    """True when git would exclude the store's data file (or the store itself)."""
    for probe in (store_rel, f"{store_rel}/memory.db"):
        if _path_ignored(toplevel, probe):
            return True
    return False


def _tracked_paths(toplevel: Path, store_rel: str) -> List[str]:
    proc = _git(toplevel, "ls-files", "--", store_rel)
    if proc is None or proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _data_files(store_dir: Path) -> Iterable[Path]:
    for name in _DATA_FILES:
        candidate = store_dir / name
        if candidate.is_file():
            yield candidate
    try:
        for path in sorted(store_dir.rglob("*.md")):
            if path.is_file() and "models" not in path.relative_to(store_dir).parts:
                yield path
    except OSError:
        return


def _stage_store(toplevel: Path, store_dir: Path, store_rel: str) -> bool:
    """Stage the store, falling back to force-adding only its data files.

    ``git add`` (not ``-f``) is preferred because it respects the ignore rules we
    just wrote — in particular the model cache. If a later/nested ignore rule
    still wins, only the known data files are force-added, never the cache.
    """
    proc = _git(toplevel, "add", "-A", "--", store_rel)
    if proc is not None and proc.returncode == 0 and _tracked_paths(toplevel, store_rel):
        return True

    files: List[str] = []
    for path in _data_files(store_dir):
        try:
            rel = path.resolve().relative_to(toplevel).as_posix()
        except (OSError, RuntimeError, ValueError):
            continue
        files.append(rel)
    if not files:
        return bool(_tracked_paths(toplevel, store_rel))

    # Keep well under the Windows command-line limit; a store can hold thousands
    # of one-file-per-memory Markdown exports.
    staged = False
    for start in range(0, len(files), 100):
        chunk = files[start:start + 100]
        added = _git(toplevel, "add", "-f", "--", *chunk)
        staged = staged or (added is not None and added.returncode == 0)
    return staged


def ensure_store_tracked(
    project_root: str | Path,
    store_dir: Optional[str | Path] = None,
    *,
    stage: bool = True,
) -> Dict[str, Any]:
    """Guarantee that the Tacit store is not excluded from git.

    Returns a small status dictionary instead of raising: a project that is not a
    git repository (or git is unavailable) must never break ``tacit init`` or
    MCP startup.
    """
    root = Path(project_root)
    if store_dir is None:
        from .config import Config

        try:
            store_dir = Config.get_memory_dir(root)
        except Exception:
            store_dir = root / ".tacit"
    store = Path(store_dir)

    toplevel = git_toplevel(root)
    if toplevel is None:
        return {
            "git_repo": False,
            "repo": None,
            "store": str(store),
            "ignored": False,
            "ignore_fixed": False,
            "staged": False,
            "tracked": False,
            "message": (
                "Not a git repository: the .tacit store is safe locally, but it will "
                "not travel with the code until this project is under git."
            ),
        }

    store_rel = _relative_to_repo(store, toplevel)
    if not store_rel:
        return {
            "git_repo": True,
            "repo": str(toplevel),
            "store": str(store),
            "ignored": False,
            "ignore_fixed": False,
            "staged": False,
            "tracked": False,
            "message": "The Tacit store is the repository root; nothing to track separately.",
        }

    # A project nested inside a larger checkout can itself be excluded by the
    # enclosing repo (test scratch dirs, vendored trees, generated workspaces).
    # In that case the enclosing repo is explicitly *not* managing this tree, and
    # rewriting its .gitignore or staging files into it would be wrong.
    project_rel = _relative_to_repo(root, toplevel)
    if project_rel and _path_ignored(toplevel, project_rel):
        return {
            "git_repo": True,
            "repo": str(toplevel),
            "store": store_rel,
            "ignored": True,
            "ignore_fixed": False,
            "staged": False,
            "tracked": False,
            "message": (
                f"'{project_rel}' is ignored by the enclosing git repository, so Tacit "
                "left that repository untouched. Initialise git inside this project if "
                "its memories should travel with it."
            ),
        }

    key = (str(toplevel), store_rel)
    if key in _ENSURED:
        cached = dict(_ENSURED[key])
        cached["message"] = "Tacit store tracking already ensured in this process."
        return cached

    was_ignored = _is_ignored(toplevel, store_rel)
    changed = _write_managed_block(toplevel / ".gitignore", store_rel)
    still_ignored = _is_ignored(toplevel, store_rel)

    staged = False
    if stage and (was_ignored or not _tracked_paths(toplevel, store_rel)):
        staged = _stage_store(toplevel, store, store_rel)

    if changed and was_ignored:
        # Stage the ignore fix too, so a later `git commit` actually persists the
        # reason the store is visible. Never stage the store's cache.
        if not still_ignored:
            _git(toplevel, "add", "--", ".gitignore")

    tracked = bool(_tracked_paths(toplevel, store_rel))

    if still_ignored:
        message = (
            "Git still ignores the .tacit store after adding the managed .gitignore "
            "block (a nested or later rule may override it). The data files were "
            "force-added, but new memories may not be tracked. Check for a "
            f"`{store_rel}` ignore rule in a nested .gitignore."
        )
    elif was_ignored or changed:
        message = (
            f"The .tacit store is now tracked by git (`{store_rel}`). Commit it with "
            "your code so a fresh clone keeps the memories. The embedding cache and "
            "SQLite WAL files stay ignored."
        )
        if staged:
            message += " Existing files were staged; nothing was committed."
    else:
        message = f"The .tacit store is already tracked by git (`{store_rel}`)."

    result = {
        "git_repo": True,
        "repo": str(toplevel),
        "store": store_rel,
        "ignored": was_ignored,
        "ignore_fixed": changed,
        "staged": staged,
        "tracked": tracked,
        "message": message,
    }
    _ENSURED[key] = dict(result)
    return result