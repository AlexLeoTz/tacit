"""Workspace-local scratch directories for tests.

`tempfile.TemporaryDirectory()` places its directory in the OS temp directory.
Where that directory cannot be chmod'd or removed — DSH's sandbox denies it on
`%TEMP%\\dsh-*` — `TemporaryDirectory.__exit__` raises `PermissionError`, so
thirteen tests failed or errored **from their own setup/teardown code**, before a
single assertion ran. That is the worst kind of red: a real regression is
indistinguishable from environment noise.

A directory inside the workspace is writable everywhere, is cleaned up the same
way, and cannot leak state onto a developer's machine.
"""

from __future__ import annotations

import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Iterator

_SCRATCH_ROOT = Path(__file__).resolve().parent / "_scratch"


def _ensure_scratch_root() -> Path:
    """Create the scratch root, marked as its own project.

    The marker matters: without it, `Config.find_project_root()` walks *up* from a
    scratch directory and finds this repository, so a test that resolves its
    project implicitly would open (and write to) the real `.tacit/memory.db` on
    disk. An empty `.git` directory makes every scratch directory its own project,
    which is exactly what a mock project is.
    """
    (_SCRATCH_ROOT / ".git").mkdir(parents=True, exist_ok=True)
    return _SCRATCH_ROOT


@contextlib.contextmanager
def workspace_tempdir(prefix: str = "tmp") -> Iterator[Path]:
    """Yield a fresh directory under ``tests/_scratch`` and remove it afterwards."""
    base = _ensure_scratch_root() / f"{prefix}-{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)
