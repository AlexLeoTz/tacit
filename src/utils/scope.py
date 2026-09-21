"""Scope-hint sanitising and automatic scope inference.

A ``scope_hint`` is a *boost*, not a project selector: it nudges memories whose
``scope`` overlaps the files an agent is working on. In practice agents pass
whatever they have to hand — a workspace path with a trailing backslash, an
absolute path to a different checkout, an escaped Windows path — and a bad hint
silently changes ranking or, worse, looks like it selected the wrong database.

Two rules keep that safe:

1. **Tacit decides the project; the caller only refines the scope.** Hints that
   are absolute paths outside the project root are discarded because they cannot
   legitimately describe this project's memories.
2. **When no usable hint is supplied, the current working directory is used.**
   "Let Tacit take the active directory" beats trusting an agent to construct a
   path correctly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

#: Hints beyond this count add no signal and only slow matching down.
MAX_HINTS = 20


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
    ``backend/app``; running at the project root yields no hint, which leaves
    ranking neutral rather than inventing a scope.
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


def scope_matches(node_scope: Sequence[str], hints: Sequence[str]) -> bool:
    """True when any stored scope path contains any hint (loose, case-insensitive).

    A loose substring match lets a caller pass a directory and still boost every
    file beneath it: hint ``src/api`` matches a node scoped to
    ``src/api/auth.py``.
    """
    if not node_scope or not hints:
        return False
    haystacks = [str(path).replace("\\", "/").lower() for path in node_scope if str(path).strip()]
    for hint in hints:
        needle = normalize_path_text(str(hint)).lower()
        if not needle:
            continue
        for haystack in haystacks:
            if needle in haystack:
                return True
    return False
