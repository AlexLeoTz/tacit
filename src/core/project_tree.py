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

import hashlib
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
#: v2: one metadata row per file (see the file-table section below).
FILE_TABLE_FILE = "file-table.json"


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


# ---------------------------------------------------------------------------
# The file table: one row of metadata per file
#
# A structure map tells a session where things are. The file table adds what a
# session cannot get without opening the file: how big it is in lines and what
# lives inside it. The mechanical half (lines, bytes, language, hash, size) is
# computed here; the description is written by an agent, because only a reader
# can say "contains the payment logic". Every row records who wrote it and when,
# and staleness is detected by comparing the stored hash/size with the file on
# disk — so a stale row is a fact, not a guess.
# ---------------------------------------------------------------------------

#: Content read when hashing. Larger files are hashed on their first chunk only,
#: and marked, because a full read of a huge asset is not worth the seconds.
HASH_CHUNK_LIMIT = 2 * 1024 * 1024
TRUNCATED_HASH_SUFFIX = ":partial"

#: Extension -> language label, for the (common) cases where it is not obvious.
LANGUAGE_BY_SUFFIX = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
    ".php": "PHP", ".rb": "Ruby", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".cs": "C#",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".vue": "Vue", ".svelte": "Svelte", ".blade.php": "Blade",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".md": "Markdown", ".rst": "reStructuredText", ".txt": "Text",
    ".tf": "Terraform", ".dockerfile": "Dockerfile", ".ini": "INI",
}

#: Files that are never worth counting lines in.
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".bmp",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".7z", ".rar", ".jar", ".war",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov",
    ".webm", ".wav", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".sqlite",
    ".db", ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".class",
)

MAX_DESCRIPTION_CHARS = 400


def normalise_rel_path(value: Any) -> str:
    """Normalise a caller-supplied project-relative path.

    Only a leading ``./`` is stripped. ``lstrip("./")`` — the obvious-looking
    one-liner — eats the dot of every dotfile, turning ``.env`` into ``env`` and
    keying the row to the wrong filename.
    """
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def file_language(rel_path: str) -> str:
    """Best-effort language label from a file name."""
    name = str(rel_path).lower()
    lowered = name.rsplit("/", 1)[-1]
    if lowered in {"dockerfile", "makefile", "procfile", "rakefile", "gemfile"}:
        return lowered.capitalize()
    for suffix, language in LANGUAGE_BY_SUFFIX.items():
        if name.endswith(suffix):
            return language
    return ""


def is_probably_binary(rel_path: str) -> bool:
    return str(rel_path).lower().endswith(BINARY_SUFFIXES)


def file_facts(root: str | Path, rel_path: str) -> Dict[str, Any]:
    """Mechanical facts about one file: lines, bytes, language, hash, mtime."""
    target = Path(root) / str(rel_path).replace("\\", "/")
    facts: Dict[str, Any] = {
        "lines": 0,
        "bytes": 0,
        "language": file_language(rel_path),
        "binary": is_probably_binary(rel_path),
        "hash": "",
        "size": 0,
        "mtime": 0.0,
    }
    try:
        stat = target.stat()
    except OSError:
        return facts

    facts["size"] = int(stat.st_size)
    facts["mtime"] = float(stat.st_mtime)

    if not facts["binary"]:
        try:
            data = target.read_bytes()
        except OSError:
            data = b""
        facts["bytes"] = len(data) if data else int(stat.st_size)
        if data:
            # Counting the newlines of a real text file is exact and cheap.
            facts["lines"] = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)

    digest = hashlib.sha256()
    fact_bytes = 0
    try:
        with target.open("rb") as handle:
            while True:
                chunk = handle.read(256 * 1024)
                if not chunk:
                    break
                if fact_bytes + len(chunk) > HASH_CHUNK_LIMIT:
                    digest.update(chunk[: max(0, HASH_CHUNK_LIMIT - fact_bytes)])
                    facts["hash"] = digest.hexdigest() + TRUNCATED_HASH_SUFFIX
                    return facts
                digest.update(chunk)
                fact_bytes += len(chunk)
    except OSError:
        return facts
    facts["hash"] = digest.hexdigest()
    return facts


def file_table_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / FILE_TABLE_FILE


def load_file_table(store_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """Read the file table, migrating a legacy ``gists.json`` on first use."""
    path = file_table_path(store_dir)
    if not path.exists():
        migrated = _migrate_gists(store_dir)
        if migrated:
            return migrated
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("files") if isinstance(data, dict) and "files" in data else data
        return rows if isinstance(rows, dict) else {}
    except (OSError, ValueError):
        return {}


def save_file_table(store_dir: str | Path, rows: Dict[str, Dict[str, Any]]) -> Path:
    path = file_table_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "files": rows}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _migrate_gists(store_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """Fold a v1 ``gists.json`` into the file table, preserving who and when."""
    legacy = gists_path(store_dir)
    if not legacy.exists():
        return {}
    try:
        old = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(old, dict) or not old:
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for key, value in old.items():
        if not isinstance(value, dict):
            continue
        rows[str(key).replace("\\", "/")] = {
            "description": str(value.get("gist") or "")[:MAX_DESCRIPTION_CHARS],
            "updated_at": float(value.get("updated_at") or 0) or time.time(),
            "by": str(value.get("by") or "unknown"),
            "migrated_from": "gists.json",
        }
    if rows:
        save_file_table(store_dir, rows)
    return rows


def set_file_row(
    root: str | Path,
    store_dir: str | Path,
    rel_path: str,
    description: Optional[str] = None,
    by: str = "ai-agent",
    refresh_facts: bool = True,
) -> Optional[Dict[str, Any]]:
    """Write or update one row, recomputing its mechanical facts from disk.

    Only the fields the caller actually changes are touched: passing no
    ``description`` keeps the existing one, which is how ``tacit files --refresh``
    updates line counts without discarding what an agent learned.
    """
    key = normalise_rel_path(rel_path)
    if not key:
        return None

    rows = load_file_table(store_dir)
    row = dict(rows.get(key) or {})
    row.setdefault("description", "")
    row["path"] = key
    row["language"] = row.get("language") or file_language(key)

    if refresh_facts:
        facts = file_facts(root, key)
        row.update(facts)
        row["analyzed_at"] = time.time()

    if description is not None:
        row["description"] = str(description).strip()[:MAX_DESCRIPTION_CHARS]
        row["updated_at"] = time.time()
        row["by"] = str(by or "unknown")

    rows[key] = row
    save_file_table(store_dir, rows)
    return row


def update_file_rows(
    root: str | Path,
    store_dir: str | Path,
    entries: Iterable[Dict[str, Any]],
    by: str = "ai-agent",
    refresh_facts: bool = True,
) -> Dict[str, Any]:
    """Write many rows in one pass — how an agent fills the table in parallel.

    Each entry is ``{"path": ..., "description": ...}``. Bad paths are reported
    per entry instead of failing the batch, so one typo cannot waste the work of
    the other nineteen descriptions.
    """
    rows = load_file_table(store_dir)
    written: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for entry in entries or []:
        raw = normalise_rel_path((entry or {}).get("path"))
        if not raw:
            errors.append({"path": "", "error": "missing path"})
            continue
        target = Path(root) / raw
        if not target.exists():
            errors.append({"path": raw, "error": "no such file or directory"})
            continue

        row = dict(rows.get(raw) or {})
        row.setdefault("description", "")
        row["path"] = raw
        row["language"] = row.get("language") or file_language(raw)
        if refresh_facts:
            row.update(file_facts(root, raw))
            row["analyzed_at"] = time.time()
        description = (entry or {}).get("description")
        if description is not None:
            row["description"] = str(description).strip()[:MAX_DESCRIPTION_CHARS]
            row["updated_at"] = time.time()
            row["by"] = str((entry or {}).get("by") or by or "unknown")
        rows[raw] = row
        written.append(row)

    save_file_table(store_dir, rows)
    return {"written": written, "errors": errors, "count": len(written)}


def snapshot_files(snapshot: Optional[Dict[str, Any]]) -> List[str]:
    """Every file path in a snapshot, in map order."""
    found: List[str] = []

    def walk(nodes: Sequence[Dict[str, Any]], rel: str) -> None:
        for node in nodes:
            name = str(node.get("name", ""))
            node_rel = f"{rel}/{name}" if rel else name
            if node.get("type") == "dir":
                walk(node.get("children") or [], node_rel)
            else:
                found.append(node_rel)

    walk((snapshot or {}).get("children") or [], "")
    return found


def pending_files(
    root: str | Path,
    store_dir: str | Path,
    limit: int = 25,
    include_facts: bool = True,
) -> Dict[str, Any]:
    """Files whose row is missing or stale, with the facts already computed.

    Stale means the file's content hash or size no longer matches the row — a
    rename is covered too, because the snapshot is rebuilt first when it is old.
    The caller only has to supply a description.
    """
    snapshot = load_snapshot(store_dir)
    if not snapshot:
        snapshot = refresh_snapshot(root, store_dir)

    paths = snapshot_files(snapshot)
    rows = load_file_table(store_dir)
    pending: List[Dict[str, Any]] = []

    for rel in paths:
        row = rows.get(rel) or {}
        facts = file_facts(root, rel) if include_facts else {}
        reasons: List[str] = []
        if not row:
            reasons.append("no row yet")
        else:
            if not str(row.get("description") or "").strip():
                reasons.append("no description")
            stored_hash = str(row.get("hash") or "")
            if stored_hash and facts and stored_hash != facts.get("hash"):
                reasons.append("content changed")
            if row.get("size") is not None and facts and int(row.get("size") or 0) != int(facts.get("size") or 0):
                if "content changed" not in reasons:
                    reasons.append("size changed")
        if reasons:
            entry: Dict[str, Any] = {"path": rel, "reasons": reasons}
            if include_facts:
                entry.update(
                    {
                        "lines": facts.get("lines", 0),
                        "bytes": facts.get("bytes", 0),
                        "language": facts.get("language", ""),
                        "binary": facts.get("binary", False),
                        "hash": facts.get("hash", ""),
                        "size": facts.get("size", 0),
                    }
                )
                if row.get("description"):
                    entry["current_description"] = row.get("description")
            pending.append(entry)

    pending.sort(key=lambda item: (-int(item.get("lines") or 0), item["path"]))
    selected = pending[: max(1, int(limit))] if limit else pending
    return {
        "total_pending": len(pending),
        "returned": len(selected),
        "total_files": len(paths),
        "described": sum(1 for rel in paths if (rows.get(rel) or {}).get("description")),
        "files": selected,
    }


def file_table_stats(root: str | Path, store_dir: str | Path) -> Dict[str, Any]:
    """Totals for the project's file table."""
    snapshot = load_snapshot(store_dir)
    paths = snapshot_files(snapshot) if snapshot else snapshot_files(refresh_snapshot(root, store_dir))
    rows = load_file_table(store_dir)

    total_lines = 0
    described = 0
    stale = 0
    languages: Dict[str, int] = {}
    for rel in paths:
        row = rows.get(rel) or {}
        total_lines += int(row.get("lines") or 0)
        if str(row.get("description") or "").strip():
            described += 1
        language = str(row.get("language") or file_language(rel) or "other")
        languages[language] = languages.get(language, 0) + 1
        facts = file_facts(root, rel)
        if row and (str(row.get("hash") or "") != str(facts.get("hash") or "")):
            stale += 1

    return {
        "files": len(paths),
        "rows": sum(1 for rel in paths if rel in rows),
        "described": described,
        "undescribed": len(paths) - described,
        "stale": stale,
        "total_lines": total_lines,
        "languages": dict(sorted(languages.items(), key=lambda item: -item[1])),
    }


def prune_file_table(root: str | Path, store_dir: str | Path) -> List[str]:
    """Drop rows whose file no longer exists; returns the removed paths."""
    rows = load_file_table(store_dir)
    removed = [key for key in rows if not (Path(root) / key).exists()]
    if removed:
        for key in removed:
            rows.pop(key, None)
        save_file_table(store_dir, rows)
    return removed


def format_lines(lines: int) -> str:
    """Compact line count: 942 -> '942', 12400 -> '12.4k', 1200000 -> '1.2M'."""
    count = int(lines or 0)
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


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
# Gists: the v1 name for a file row's description
#
# Kept as a thin compatibility layer over the file table so older callers (and
# any `gists.json` already on disk) keep working.
# ---------------------------------------------------------------------------

def gists_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / GISTS_FILE


def load_gists(store_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """The described rows, in the v1 ``gists.json`` shape."""
    view: Dict[str, Dict[str, Any]] = {}
    for key, row in load_file_table(store_dir).items():
        description = str(row.get("description") or "").strip()
        if not description:
            continue
        view[key] = {
            "gist": description,
            "updated_at": row.get("updated_at") or 0,
            "by": row.get("by") or "unknown",
        }
    return view


def set_gist(
    store_dir: str | Path,
    rel_path: str,
    gist: str,
    author: str = "ai-agent",
) -> Optional[Dict[str, Any]]:
    """Store (or clear, with an empty gist) the description for one file.

    No filesystem facts are computed here because no project root is known; use
    :func:`set_file_row` when the root is available, which also records lines,
    size and content hash.
    """
    key = normalise_rel_path(rel_path)
    if not key:
        return None
    rows = load_file_table(store_dir)
    row = dict(rows.get(key) or {})
    row.setdefault("description", "")
    row["path"] = key
    row["language"] = row.get("language") or file_language(key)

    text = str(gist or "").strip()
    if not text:
        row["description"] = ""
        if not any(value for field, value in row.items() if field not in {"path", "description", "language"}):
            # Nothing left worth keeping: drop the row entirely.
            rows.pop(key, None)
            save_file_table(store_dir, rows)
            return None
    else:
        row["description"] = text[:MAX_DESCRIPTION_CHARS]
        row["updated_at"] = time.time()
        row["by"] = str(author or "unknown")
    rows[key] = row
    save_file_table(store_dir, rows)
    return row


def prune_gists(store_dir: str | Path, existing_paths: Iterable[str]) -> List[str]:
    """Drop rows whose file no longer exists; returns the removed keys."""
    keep = {str(path).replace("\\", "/") for path in existing_paths}
    rows = load_file_table(store_dir)
    removed = [key for key in rows if key not in keep]
    if removed:
        for key in removed:
            rows.pop(key, None)
        save_file_table(store_dir, rows)
    return removed


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _row_annotation(rel_path: str, rows: Dict[str, Dict[str, Any]], include_lines: bool) -> str:
    """``(12.4k LOC) # description`` for one file, or ``""``."""
    row = rows.get(rel_path) or {}
    parts: List[str] = []
    if include_lines and row.get("lines"):
        parts.append(f"({format_lines(int(row['lines']))} LOC)")
    description = str(row.get("description") or "").strip().replace("\n", " ")
    if description:
        parts.append(f"# {description}")
    return ("   " + " ".join(parts)) if parts else ""


def render_tree(
    snapshot: Dict[str, Any],
    rows: Optional[Dict[str, Dict[str, Any]]] = None,
    path_prefix: str = "",
    max_lines: int = 400,
    include_lines: bool = True,
) -> str:
    """Render a snapshot as an indented outline, annotated from the file table."""
    rows = rows or {}
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
                lines.append(f"{'  ' * depth}- {name}{_row_annotation(node_rel, rows, include_lines)}")

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
    rows = load_file_table(store_dir) if (include_gists and settings.get("gists", True)) else {}
    body = render_tree(snapshot, rows=rows, path_prefix=path_prefix, max_lines=max_lines)
    summary = snapshot_summary(store_dir) or ""
    legend = "\n(* = git repository; `(n LOC)` = lines of code; `#` = stored description)"
    described = sum(1 for row in rows.values() if str(row.get("description") or "").strip())
    if rows:
        legend += f"\n({described}/{len(rows)} rows described · `tacit files --pending` lists the rest)"
    return f"{body}{legend}\n({summary})"
