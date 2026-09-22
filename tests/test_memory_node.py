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


def test_auto_title_uses_the_first_meaningful_line():
    """Titles are embedded into the vector index, so a raw body slice is a poor key.

    The old behaviour took ``content[:50]`` verbatim, carrying ``###`` markers
    and embedded newlines into the title and breaking one-line display.
    """
    node = MemoryNode(
        content="### 1. Context & Problem Statement\nLarge multi-gigabyte video files...",
        type="architecture",
    )

    assert node.title == "Architecture: Context & Problem Statement"
    assert "\n" not in node.title
    assert "#" not in node.title


def test_auto_title_skips_blank_leading_lines_and_list_markers():
    node = MemoryNode(content="\n\n  \n- Fixed the pool size\nmore text", type="error")

    assert node.title == "Error: Fixed the pool size"


def test_auto_title_truncates_a_long_headline():
    node = MemoryNode(content="X" * 200, type="decision")

    assert node.title.startswith("Decision: ")
    assert node.title.endswith("...")
    assert len(node.title) <= len("Decision: ") + 60


def test_auto_title_falls_back_when_there_is_nothing_usable():
    assert MemoryNode(content="", type="context").title == "Context: Memory Node"
    assert MemoryNode(content="###\n", type="context").title == "Context: Memory Node"


def test_auto_summary_is_single_line_prose():
    node = MemoryNode(content="### Heading\n\nBody line one.\nBody line two.")

    assert "\n" not in node.summary
    assert "Heading Body line one." in node.summary


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
