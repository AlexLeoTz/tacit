"""Unit tests for SQLite storage layer and FTS5 search."""

import tempfile
from pathlib import Path
import pytest

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        storage = MemoryStorage(db_path)
        yield storage


def test_storage_add_and_get(temp_storage):
    node = MemoryNode(
        content="Testing SQLite storage layer.",
        type="decision",
        summary="Test SQLite",
        tags=["test", "sqlite"],
    )

    success = temp_storage.add_memory(node)
    assert success is True

    # Duplicate should fail
    assert temp_storage.add_memory(node) is False

    retrieved = temp_storage.get_memory(node.id)
    assert retrieved is not None
    assert retrieved.id == node.id
    assert retrieved.content == node.content
    assert retrieved.tags == ["test", "sqlite"]
    assert retrieved.verify() is True


def test_storage_search_full_text(temp_storage):
    node1 = MemoryNode(
        content="Migrating database from MySQL to PostgreSQL for JSONB features.",
        type="architecture",
        title="Database Migration",
        tags=["database", "postgres"],
    )
    node2 = MemoryNode(
        content="Fixed Redis cache invalidation bug on user logout.",
        type="error",
        title="Redis Invalidation Fix",
        tags=["redis", "cache"],
    )

    temp_storage.add_memory(node1)
    temp_storage.add_memory(node2)

    results = temp_storage.search_full_text("PostgreSQL")
    assert len(results) >= 1
    assert results[0].id == node1.id

    results_type = temp_storage.search_full_text("PostgreSQL", memory_type="architecture")
    assert len(results_type) == 1

    results_none = temp_storage.search_full_text("Elasticsearch")
    assert len(results_none) == 0


def test_storage_pagination_and_counts(temp_storage):
    for i in range(15):
        temp_storage.add_memory(
            MemoryNode(
                content=f"Memory record #{i}",
                type="command" if i % 2 == 0 else "decision",
            )
        )

    assert temp_storage.get_count() == 15
    assert temp_storage.get_count("command") == 8
    assert temp_storage.get_count("decision") == 7

    page1 = temp_storage.get_all(limit=10, offset=0)
    assert len(page1) == 10

    page2 = temp_storage.get_all(limit=10, offset=10)
    assert len(page2) == 5


def test_storage_delete_and_clear(temp_storage):
    node1 = MemoryNode(content="Node to delete", type="decision")
    node2 = MemoryNode(content="Node to keep", type="architecture")

    temp_storage.add_memory(node1)
    temp_storage.add_memory(node2)

    assert temp_storage.get_count() == 2

    # Delete single node
    deleted = temp_storage.delete_memory(node1.id)
    assert deleted is True
    assert temp_storage.get_memory(node1.id) is None
    assert temp_storage.get_count() == 1

    # Clear all
    cleared = temp_storage.clear_all_memories()
    assert cleared == 1
    assert temp_storage.get_count() == 0
