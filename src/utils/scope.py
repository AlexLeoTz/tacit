"""Scope sanitising, matching and automatic scope inference.

A ``scope_hint`` is a **filter**, not a nudge: only memories whose stored
``scope`` matches one of the supplied paths are ranked, and with no usable hint
every memory in the current workspace store is ranked. Cross-repo leakage is
therefore impossible by construction — a memory recorded against a different
subsystem (or a different repository) cannot appear in the briefing.

Three rules keep that safe:

1. **Tacit decides the project; the caller only refines the scope.** Hints that
   are absolute paths outside the project root are discarded because they cannot
   legitimately describe this project's memories.
2. **When no usable hint is supplied, the current working directory is used.**
   "Let Tacit take the active directory" beats trusting an agent to construct a
   path correctly.
3. **Project-wide memories always match.** A memory scoped to the project itself
   (see :func:`scope_is_project_wide`) is institutional knowledge about the whole
   workspace, so it survives every scope filter — otherwise every past memory
   recorded without a file path would silently disappear.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

#: Hints beyond this count add no signal and only slow matching down.
MAX_HINTS = 20

#: Scope entries that explicitly mean "the whole project".
PROJECT_WIDE_MARKERS = {".", "/", "*", ""}


def _coerce(hints: Optional[Iterable[str] | str]) -> List[str]:
    if hints is None:
        return []
    if isinstance(hints, str):
        return [hints]
    return [str(hint) for hint in hints if hint is not None]


def normalize_path_text(value: str) -> str:
    """Trim, unquote and unify separators on a caller-supplied path fragment."""
    text = value.strip().strip('"').strip("'").strip()
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def normalize_scope_hints(
    hints: Optional[Iterable[str] | str],
    project_root: Optional[Path] = None,
    limit: int = MAX_HINTS,
) -> List[str]:
    """Return usable, deduplicated, project-relative scope hints.

    Drops empty entries, ``.`` markers, and absolute paths that fall outside
    ``project_root`` (converting absolute paths *inside* it to relative form).
    """
    root: Optional[Path] = None
    if project_root is not None:
        try:
            root = Path(project_root).resolve()
        except OSError:
            root = None

    cleaned: List[str] = []
    seen = set()

    for raw in _coerce(hints):
        text = normalize_path_text(raw)
        if not text or text == ".":
            continue

        candidate = Path(text)
        if candidate.is_absolute():
            if root is None:
                # Without a project root we cannot tell whether this is ours.
                continue
            try:
                text = normalize_path_text(str(candidate.resolve().relative_to(root)))
            except (OSError, ValueError):
                # An absolute path outside the project cannot scope its memories.
                continue
            if not text or text == ".":
                continue

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

        if len(cleaned) >= max(1, limit):
            break

    return cleaned


def infer_scope_from_cwd(
    project_root: Optional[Path],
    cwd: Optional[Path] = None,
) -> List[str]:
    """Derive the active scope from the working directory.

    Running inside ``<project>/backend/app`` scopes the briefing to
    ``backend/app``; running at the project root yields no hint, which means the
    whole workspace is ranked rather than an invented scope.
    """
    if project_root is None:
        return []
    try:
        root = Path(project_root).resolve()
        here = Path(cwd or Path.cwd()).resolve()
    except OSError:
        return []

    if here == root:
        return []
    try:
        relative = here.relative_to(root)
    except ValueError:
        return []

    text = normalize_path_text(str(relative))
    return [text] if text and text != "." else []


def resolve_scope_hints(
    hints: Optional[Iterable[str] | str],
    project_root: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> List[str]:
    """Sanitise caller hints, falling back to the active directory.

    This is the function every entry point should call, so the MCP tools and the
    CLI cannot diverge in how they interpret a scope.
    """
    cleaned = normalize_scope_hints(hints, project_root=project_root)
    if cleaned:
        return cleaned
    return infer_scope_from_cwd(project_root, cwd=cwd)


def _segments(text: str) -> List[str]:
    return [part for part in normalize_path_text(text).lower().split("/") if part]


def scope_matches(node_scope: Sequence[str], hints: Sequence[str]) -> bool:
    """True when a stored scope path and a hint describe the same file or subtree.

    Matching happens on **path segments**, in both directions, so a hint naming a
    directory (``backend/app``) matches a memory scoped to a file inside it
    (``backend/app/Models/Film.php``) and vice versa. A bare filename hint
    (``Film.php``, no separator) matches any stored path ending in that name,
    which is how agents usually refer to a file they are editing.

    Segment matching replaces the old loose substring test on purpose: it keeps
    ``app`` from matching ``myapp`` while still tolerating the directory/file
    asymmetry that agents produce.
    """
    if not node_scope or not hints:
        return False
    haystacks = [_segments(path) for path in node_scope if str(path).strip()]
    for hint in hints:
        needle = _segments(hint)
        if not needle:
            continue
        for haystack in haystacks:
            if not haystack:
                continue
            # A single segment is either a directory name (`backend`) or a file
            # name (`FilmManager.php`); both are matched anywhere in the stored
            # path, but only as a whole segment, so `app` never matches `myapp`.
            if len(needle) == 1:
                if needle[0] in haystack:
                    return True
                continue
            shorter, longer = (needle, haystack) if len(needle) <= len(haystack) else (haystack, needle)
            if longer[: len(shorter)] == shorter:
                return True
    return False


def scope_is_project_wide(
    node_scope: Sequence[str],
    project_root: Optional[Path] = None,
) -> bool:
    """True when the node is scoped to the project as a whole, not a subsystem.

    Recognises the explicit markers (``.``, ``/``, ``*``) and an entry equal to
    the project directory's own name — the scope Tacit auto-fills when an agent
    records knowledge that applies to the entire workspace.
    """
    if not node_scope:
        return True
    project_name = ""
    if project_root is not None:
        try:
            project_name = Path(project_root).resolve().name.lower()
        except (OSError, RuntimeError):
            project_name = ""
    for entry in node_scope:
        text = str(entry).strip()
        if text in PROJECT_WIDE_MARKERS:
            return True
        normalized = normalize_path_text(text).lower()
        if normalized and project_name and normalized == project_name:
            return True
    return False


def node_matches_scope(
    node_scope: Sequence[str],
    hints: Sequence[str],
    project_root: Optional[Path] = None,
) -> bool:
    """The scope FILTER used by every read surface.

    No hints means "everything in this workspace store". With hints, a node is
    kept when it matches one of them or when it is project-wide knowledge.
    """
    if not hints:
        return True
    if scope_is_project_wide(node_scope, project_root=project_root):
        return True
    return scope_matches(node_scope, hints)
