"""Unit tests for Search components (FullTextSearch, TemporalSearch, BloomFilter)."""

import tempfile
from pathlib import Path
import pytest
from datetime import datetime, timezone

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.search.full_text import FullTextSearch
from src.search.temporal import TemporalSearch
from src.search.bloom_filter import BloomFilter


@pytest.fixture
def search_fixture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "search_test.db"
        storage = MemoryStorage(db_path)
        fts = FullTextSearch(storage)
        temporal = TemporalSearch(storage)
        yield storage, fts, temporal


def test_full_text_search_with_tags(search_fixture):
    storage, fts, _ = search_fixture

    node1 = MemoryNode(
        content="Configured HTTPS and SSL certificates on Nginx ingress.",
        type="decision",
        tags=["nginx", "security", "ssl"],
    )
    node2 = MemoryNode(
        content="Set up Let's Encrypt auto-renewal cronjob on VPS.",
        type="command",
        tags=["cron", "ssl"],
    )

    storage.add_memory(node1)
    storage.add_memory(node2)

    results = fts.search("Nginx", tags=["security"])
    assert len(results) == 1
    assert results[0].id == node1.id


def test_temporal_search(search_fixture):
    storage, _, temporal = search_fixture

    node = MemoryNode(
        content="Recent decision recorded today.",
        type="decision",
    )
    storage.add_memory(node)

    recent = temporal.get_recent(days=1)
    assert len(recent) == 1
    assert recent[0].id == node.id

    context = temporal.get_by_timeframe(timeframe="week")
    assert len(context) == 1

    grouped = temporal.group_by_type([node])
    assert len(grouped["decision"]) == 1


def test_bloom_filter():
    bf = BloomFilter(expected_elements=100, false_positive_rate=0.01)
    items = ["jwt-auth", "sqlite-fts", "docker-compose", "nginx-ssl"]

    for item in items:
        bf.add(item)

    for item in items:
        assert item in bf

    assert ("random-unknown-item-12345" in bf) is False
