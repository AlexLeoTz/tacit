"""Unit tests for MemoryNode data structure and cryptographic hashing."""

import json
import uuid
import pytest
from datetime import datetime, timezone

from src.core.memory_node import MemoryNode
from src.utils.hashing import calculate_content_hash, calculate_merkle_root


def test_memory_node_creation_and_hashes():
    """Verify that MemoryNode correctly populates hashes, summary, and title on creation."""
    node = MemoryNode(
        content="Migrated authentication from sessions to stateless JWT tokens.",
        type="decision",
        tags=["auth", "jwt"],
        impact="high",
    )

    assert node.id is not None
    assert node.summary != ""
    assert "Migrated" in node.summary
    assert node.title.startswith("Decision:")
    assert node.content_hash != ""
    assert node.merkle_root != ""
    assert node.verify() is True


def test_memory_node_serialization():
    """Verify dictionary serialization and deserialization roundtrip."""
    original = MemoryNode(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).timestamp(),
        content="Custom storage optimization",
        summary="Storage opt",
        title="Architecture: Storage",
        type="architecture",
        tags=["db", "sqlite"],
        scope=["src/core/storage.py"],
        impact="high",
        parents=["parent-node-123"],
        children=[],
        related=["rel-456"],
        author="agent-007",
        metadata={"version": 1, "flag": True},
    )

    data_dict = original.to_dict()
    assert isinstance(data_dict["tags"], str)  # JSON encoded for SQLite
    assert isinstance(data_dict["parents"], str)

    restored = MemoryNode.from_dict(data_dict)
    assert restored.id == original.id
    assert restored.timestamp == original.timestamp
    assert restored.content == original.content
    assert restored.tags == ["db", "sqlite"]
    assert restored.parents == ["parent-node-123"]
    assert restored.metadata == {"version": 1, "flag": True}
    assert restored.verify() is True


def test_memory_node_tamper_detection():
    """Verify that modifying content hash or content fails verification."""
    node = MemoryNode(
        content="Original content",
        summary="Summary",
        title="Title",
        type="decision",
    )
    assert node.verify() is True

    # Tampered node
    tampered_data = node.to_dict()
    tampered_data["content"] = "Tampered content"
    tampered_node = MemoryNode.from_dict(tampered_data)

    assert tampered_node.verify() is False
