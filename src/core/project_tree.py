"""A cheap, agent-facing map of the workspace: structure, never source code.

A new session can learn *where things are* in one call instead of exploring the
tree with dozens of file reads. The snapshot stores names and nesting only — no
file contents — plus optional one-line gists an agent can refresh as it learns
what a file actually does.

Two shapes of workspace are supported:

* a single repository, and
* a parent directory holding several of them (``backend`` + ``frontend``), which
  is detected by looking for ``.git`` and can be overridden with an explicit
  ``repos`` list in the store's config.

Everything lives inside the project's store (``<store>/project-tree.json`` and
``<store>/gists.json``), so ``tacit move`` carries the map with the memories and
nothing extra appears in the repository.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Directories that are noise in a structural map (dependency trees, build
#: output, caches). Matched case-insensitively by name, at any depth.
IGNORED_DIR_NAMES = {
    ".git", ".hg", ".svn", ".tacit",
    "node_modules", "bower_components", "vendor", "Pods", "DerivedData",
    ".venv", "venv", "env", ".env.d", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "site-packages",
    "dist", "build", "out", "target", "coverage", "htmlcov", ".next",
    ".nuxt", ".svelte-kit", ".parcel-cache", ".angular", ".gradle",
    ".terraform", ".serverless", ".cache", ".idea", ".vscode",
    "storage", "tmp", "temp", "logs", "memory-export", ".dart_tool",
}

#: Files that carry no structural information.
IGNORED_FILE_SUFFIXES = (
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".class", ".o", ".obj",
    ".log", ".tmp", ".swp", ".lock",
)
IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

DEFAULT_MAX_DEPTH = 5
DEFAULT_MAX_ENTRIES = 4000
MAX_GIST_CHARS = 240

CONFIG_SECTION = "project_tree"
CONFIG_FILE = "config.json"
SNAPSHOT_FILE = "project-tree.json"
GISTS_FILE = "gists.json"


# ---------------------------------------------------------------------------
# Store-side configuration
# ---------------------------------------------------------------------------

def load_config(store_dir: str | Path) -> Dict[str, Any]:
    """Read the store's config, returning ``{}`` when it does not exist yet."""
    path = Path(store_dir) / CONFIG_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(store_dir: str | Path, config: Dict[str, Any]) -> None:
    path = Path(store_dir) / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def tree_settings(store_dir: str | Path) -> Dict[str, Any]:
    """Project-tree settings with defaults applied."""
    section = load_config(store_dir).get(CONFIG_SECTION) or {}
    if not isinstance(section, dict):
        section = {}
    return {
        "enabled": bool(section.get("enabled", False)),
        "max_depth": int(section.get("max_depth", DEFAULT_MAX_DEPTH)),
        "max_entries": int(section.get("max_entries", DEFAULT_MAX_ENTRIES)),
        "repos": [str(entry) for entry in (section.get("repos") or [])],
        "gists": bool(section.get("gists", True)),
        "ignore": [str(entry) for entry in (section.get("ignore") or [])],
    }


def update_tree_settings(store_dir: str | Path, **changes: Any) -> Dict[str, Any]:
    """Merge ``changes`` into the project-tree section and return the result."""
    config = load_config(store_dir)
    section = config.get(CONFIG_SECTION)
    if not isinstance(section, dict):
        section = {}
    section.update(changes)
    config[CONFIG_SECTION] = section
    save_config(store_dir, config)
    return tree_settings(store_dir)


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------

def _is_ignored_dir(name: str, extra: Sequence[str]) -> bool:
    lowered = name.lower()
    if lowered in IGNORED_DIR_NAMES:
        return True
    return any(lowered == pattern.lower() for pattern in extra)


def discover_repos(
    root: str | Path,
    max_depth: int = 3,
    extra_ignores: Sequence[str] = (),
) -> List[str]:
    """Return project roots under ``root``, as store-relative POSIX paths.

    A repository is any directory containing ``.git`` (a directory for a normal
    clone, a file for a worktree or submodule). The root itself is reported as
    ``"."`` when it is one, so a single-repo workspace and a backend+frontend
    parent produce the same shape of answer.
    """
    base = Path(root)
    found: List[str] = []

    def has_git(path: Path) -> bool:
        return (path / ".git").exists()

    if has_git(base):
        found.append(".")

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if not is_dir or _is_ignored_dir(entry.name, extra_ignores):
                continue
            child = Path(entry.path)
            if has_git(child):
                found.append(child.relative_to(base).as_posix())
            walk(child, depth + 1)

    walk(base, 1)
    if found and "." in found and len(found) > 1:
        # Nested repos below the root repo (a monorepo with vendored checkouts)
        # are still listed; the root stays first so the map reads top-down.
        found = ["."] + [item for item in found if item != "."]
    return found


# ---------------------------------------------------------------------------
# Snapshot building
# ---------------------------------------------------------------------------

def _walk_tree(
    directory: Path,
    depth: int,
    max_depth: int,
    extra_ignores: Sequence[str],
    budget: Dict[str, Any],
) -> List[Dict[str, Any]]:
    children: List[Dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(directory), key=lambda e: (not _is_dir(e), e.name.lower()))
    except OSError:
        return children

    for entry in entries:
        if budget["count"] >= budget["max_entries"]:
            budget["truncated"] = True
            return children
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            if _is_ignored_dir(entry.name, extra_ignores) or depth >= max_depth:
                continue
            budget["count"] += 1
            node = {
                "name": entry.name,
                "type": "dir",
                "children": _walk_tree(
                    Path(entry.path), depth + 1, max_depth, extra_ignores, budget
                ),
            }
            if (Path(entry.path) / ".git").exists():
                node["repo"] = True
            children.append(node)
        else:
            if entry.name in IGNORED_FILE_NAMES:
                continue
            if entry.name.lower().endswith(IGNORED_FILE_SUFFIXES):
                continue
            budget["count"] += 1
            children.append({"name": entry.name, "type": "file"})
    return children


def _is_dir(entry: "os.DirEntry[str]") -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def build_snapshot(root: str | Path, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Walk ``root`` and return the structural snapshot payload."""
    settings = settings or {}
    max_depth = int(settings.get("max_depth", DEFAULT_MAX_DEPTH))
    max_entries = int(settings.get("max_entries", DEFAULT_MAX_ENTRIES))
    extra_ignores = settings.get("ignore") or []
    explicit_repos = settings.get("repos") or []

    base = Path(root)
    budget: Dict[str, Any] = {"count": 0, "max_entries": max_entries, "truncated": False}
    children = _walk_tree(base, 1, max_depth, extra_ignores, budget)

    repos = explicit_repos or discover_repos(base, extra_ignores=extra_ignores)
    return {
        "generated_at": time.time(),
        "root": str(base),
        "repos": repos,
        "entry_count": budget["count"],
        "truncated": bool(budget["truncated"]),
        "max_depth": max_depth,
        "children": children,
    }


def snapshot_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / SNAPSHOT_FILE


def save_snapshot(store_dir: str | Path, snapshot: Dict[str, Any]) -> Path:
    path = snapshot_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path


def load_snapshot(store_dir: str | Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(snapshot_path(store_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def refresh_snapshot(root: str | Path, store_dir: str | Path) -> Dict[str, Any]:
    """Rebuild and persist the snapshot using the store's saved settings."""
    settings = tree_settings(store_dir)
    snapshot = build_snapshot(root, settings)
    save_snapshot(store_dir, snapshot)
    return snapshot


def snapshot_summary(store_dir: str | Path) -> Optional[str]:
    """One line describing the stored map, or ``None`` when there is none."""
    snapshot = load_snapshot(store_dir)
    if not snapshot:
        return None
    repos = snapshot.get("repos") or []
    parts = [f"{snapshot.get('entry_count', 0)} entries"]
    if repos and repos != ["."]:
        parts.append(f"{len(repos)} repos")
    age = time.time() - float(snapshot.get("generated_at") or 0)
    parts.append(f"refreshed {_human_age(age)} ago")
    if snapshot.get("truncated"):
        parts.append("truncated")
    return ", ".join(parts)


def _human_age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(max(0, seconds))}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    if seconds < 172800:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


# ---------------------------------------------------------------------------
# Gists: what a file actually contains, in one line
# ---------------------------------------------------------------------------

def gists_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / GISTS_FILE


def load_gists(store_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(gists_path(store_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_gist(
    store_dir: str | Path,
    rel_path: str,
    gist: str,
    author: str = "ai-agent",
) -> Optional[Dict[str, Any]]:
    """Store (or clear, with an empty gist) the note for one file."""
    key = str(rel_path).replace("\\", "/").strip().lstrip("./")
    if not key:
        return None
    gists = load_gists(store_dir)
    if not gist.strip():
        gists.pop(key, None)
    else:
        gists[key] = {
            "gist": gist.strip()[:MAX_GIST_CHARS],
            "updated_at": time.time(),
            "by": author,
        }
    path = gists_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gists, indent=2), encoding="utf-8")
    return gists.get(key)


def prune_gists(store_dir: str | Path, existing_paths: Iterable[str]) -> List[str]:
    """Drop gists whose file no longer exists; returns the removed keys."""
    keep = {str(path).replace("\\", "/") for path in existing_paths}
    gists = load_gists(store_dir)
    removed = [key for key in gists if key not in keep]
    if removed:
        for key in removed:
            gists.pop(key, None)
        gists_path(store_dir).write_text(json.dumps(gists, indent=2), encoding="utf-8")
    return removed


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _gist_for(rel_path: str, gists: Dict[str, Dict[str, Any]]) -> str:
    entry = gists.get(rel_path) or {}
    text = str(entry.get("gist") or "").strip()
    if not text:
        return ""
    return text.replace("\n", " ")


def render_tree(
    snapshot: Dict[str, Any],
    gists: Optional[Dict[str, Dict[str, Any]]] = None,
    path_prefix: str = "",
    max_lines: int = 400,
) -> str:
    """Render a snapshot as an indented outline, optionally gist-annotated."""
    gists = gists or {}
    prefix = path_prefix.replace("\\", "/").strip("/")
    lines: List[str] = []

    def walk(nodes: Sequence[Dict[str, Any]], depth: int, rel: str) -> None:
        if len(lines) >= max_lines:
            return
        for node in nodes:
            name = str(node.get("name", ""))
            node_rel = f"{rel}/{name}" if rel else name
            marker = " *" if node.get("repo") else ""
            if node.get("type") == "dir":
                lines.append(f"{'  ' * depth}- {name}/{marker}")
                walk(node.get("children") or [], depth + 1, node_rel)
            else:
                annotation = _gist_for(node_rel, gists)
                suffix = f"   # {annotation}" if annotation else ""
                lines.append(f"{'  ' * depth}- {name}{suffix}")

    def find(nodes: Sequence[Dict[str, Any]], rel: str) -> Optional[List[Dict[str, Any]]]:
        if not rel:
            return list(nodes)
        head, _, rest = rel.partition("/")
        for node in nodes:
            if str(node.get("name")) == head:
                if node.get("type") == "file":
                    return [node] if not rest else []
                return find(node.get("children") or [], rest)
        return None

    start = find(snapshot.get("children") or [], prefix)
    if start is None:
        return f"(no such path in the snapshot: {prefix})"

    root_name = Path(str(snapshot.get("root") or "project")).name or "project"
    header = root_name + ("/" + prefix if prefix else "")
    lines.append(header)
    walk(start, 1, prefix)

    if len(lines) >= max_lines:
        lines.append(f"... (truncated at {max_lines} lines)")
    if snapshot.get("truncated"):
        lines.append(
            f"... (snapshot capped at {snapshot.get('entry_count')} entries; "
            "raise project_tree.max_entries to see more)"
        )
    return "\n".join(lines)


def render_stored(
    root: str | Path,
    store_dir: str | Path,
    path_prefix: str = "",
    include_gists: bool = True,
    max_lines: int = 400,
) -> str:
    """Render the stored snapshot, or explain how to create one."""
    snapshot = load_snapshot(store_dir)
    if not snapshot:
        return (
            "No project structure has been captured for this workspace yet.\n"
            "Create one with `tacit init` (answer yes to keeping a project tree) "
            "or `tacit structure --refresh`."
        )
    settings = tree_settings(store_dir)
    gists = load_gists(store_dir) if (include_gists and settings.get("gists", True)) else {}
    body = render_tree(snapshot, gists=gists, path_prefix=path_prefix, max_lines=max_lines)
    summary = snapshot_summary(store_dir) or ""
    legend = "\n(* = git repository; `#` = stored file gist)" if gists else "\n(* = git repository)"
    return f"{body}{legend}\n({summary})"
