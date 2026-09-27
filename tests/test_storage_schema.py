"""Schema bootstrap: created once in one transaction, then never re-issued.

This behaviour is load-bearing for performance and was measured before it was
changed: opening a store re-ran all eleven `CREATE TABLE/INDEX IF NOT EXISTS`
statements on **every command**, and because Python's `sqlite3` runs DDL in
autocommit each statement was its own commit — eleven fsyncs, ~3.7 s on a cold
store and ~4.5 s to open an existing one. A `tacit` command was spending almost
five seconds rebuilding tables that already existed.

The fix has two parts, both guarded here:

1. the DDL runs inside one explicit transaction, and
2. a database already at ``SCHEMA_VERSION`` skips it entirely.

The assertions are about *statements executed*, not wall-clock time, so they are
deterministic; the single timing check at the end is a generous smoke guard
against the old behaviour returning unnoticed.
"""

import shutil
import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from src.core.storage import SCHEMA_VERSION, MemoryStorage


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_schema_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def db_path(tmp_dir):
    # Unique per test: a store left behind by an earlier test must never make the
    # next one look like a database that already exists.
    return tmp_dir / uuid.uuid4().hex / ".tacit" / "memory.db"


def open_traced(db_path, statements):
    """Open a store, recording every SQL statement the bootstrap executes."""

    class Traced(MemoryStorage):
        def _get_connection(self) -> sqlite3.Connection:
            conn = super()._get_connection()
            conn.set_trace_callback(statements.append)
            return conn

    return Traced(db_path)


def ddl_statements(statements):
    return [
        s for s in statements
        if s.strip().upper().startswith(("CREATE", "ALTER", "DROP"))
    ]


def test_a_fresh_store_creates_the_schema_and_stamps_the_version(db_path):
    statements = []
    store = open_traced(db_path, statements)

    assert store._fts_available is True
    assert ddl_statements(statements), "a new database must create its schema"

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert version == SCHEMA_VERSION
    assert {"memories", "edges", "lifecycle_events", "pinned_memories"} <= tables


def test_reopening_a_current_store_executes_no_ddl(db_path):
    """The whole point: an existing project opens without touching the schema."""
    open_traced(db_path, [])

    statements = []
    store = open_traced(db_path, statements)

    assert ddl_statements(statements) == []
    assert store._fts_available is True
    # Only the cheap probes are allowed: the version and availability lookups.
    assert all("SELECT" in s.upper() or "PRAGMA" in s.upper() for s in statements)


def test_a_legacy_store_is_migrated_and_then_skipped(db_path):
    """A database predating the version marker (or missing a table) still heals."""
    open_traced(db_path, [])

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 0")
        conn.execute("DROP TABLE IF EXISTS pinned_memories")

    statements = []
    open_traced(db_path, statements)

    assert ddl_statements(statements), "a stale version must re-run the DDL"

    with sqlite3.connect(db_path) as conn:
        restored = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'pinned_memories'"
        ).fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert restored == 1
    assert version == SCHEMA_VERSION

    # ...and once healed, it is skipped again.
    statements = []
    open_traced(db_path, statements)
    assert ddl_statements(statements) == []


def test_schema_creation_is_one_transaction(db_path):
    """Eleven autocommitted DDL statements were eleven fsyncs; one is enough."""
    statements = []
    open_traced(db_path, statements)

    begins = [s for s in statements if s.strip().upper() == "BEGIN"]
    assert len(begins) == 1, "the schema must be created inside a single transaction"


def test_reopening_a_store_stays_fast(db_path):
    """Smoke guard, not a benchmark: the old code took seconds per open."""
    open_traced(db_path, [])

    started = time.perf_counter()
    for _ in range(20):
        MemoryStorage(db_path)
    elapsed = time.perf_counter() - started

    # 20 opens at ~2 ms each. The pre-fix behaviour was ~0.9-4 s per open, so this
    # fails loudly if the fast path is ever lost, while leaving huge headroom for a
    # slow CI disk.
    assert elapsed < 3.0, f"reopening an existing store took {elapsed:.2f}s for 20 opens"
