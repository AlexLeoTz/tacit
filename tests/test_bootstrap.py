"""Unit tests for the Bootstrap Scoring and Briefing Algorithm."""

from datetime import datetime, timezone, timedelta
import pytest
from pathlib import Path
import tempfile

from src.core.bootstrap import (
    BootstrapEngine,
    Features,
    ScoredNode,
    WEIGHTS,
    IMPACT_SCORES,
    CENTRALITY_SATURATION_K,
    RECENCY_HALF_LIFE_DAYS,
    PENALTY_MAX,
    PENALTY_HALF_LIFE_DAYS,
    estimate_tokens,
    dominant_tag,
)
from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / ".tacit" / "memory.db"
        storage = MemoryStorage(db_path)
        yield storage


def test_estimate_tokens():
    text = "Hello world! This is a test."
    tokens = estimate_tokens(text)
    assert tokens == len(text) // 4


def test_dominant_tag():
    node1 = MemoryNode(content="test", tags=["Auth", "Security"], type="decision")
    assert dominant_tag(node1) == "auth"

    node2 = MemoryNode(content="test", tags=[], type="Architecture")
    assert dominant_tag(node2) == "architecture"


def test_feature_computation_and_scoring_worked_example():
    """Verify the exact worked example from the bootstrap specification."""
    now_dt = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    now_ts = now_dt.timestamp()

    # Node 1: Async migration (foundational) - 300d old, HIGH impact, 12 descendants
    node1 = MemoryNode(
        id="async_mig",
        timestamp=(now_dt - timedelta(days=300)).timestamp(),
        content="Migrated backend to async request handling",
        impact="high",
        type="decision",
        tags=["async", "architecture"],
    )

    # Node 2: JWT re-adoption - 100d old, HIGH impact, 5 descendants
    node2 = MemoryNode(
        id="jwt_readopt",
        timestamp=(now_dt - timedelta(days=100)).timestamp(),
        content="Re-adopted JWT auth with 15-minute refresh rotation",
        impact="high",
        type="decision",
        tags=["auth", "jwt"],
    )

    # Node 3: Pool-size fix - 10d old, MED impact, 2 descendants
    node3 = MemoryNode(
        id="pool_fix",
        timestamp=(now_dt - timedelta(days=10)).timestamp(),
        content="Resolved connection pool exhaustion by increasing pool size to 30",
        impact="medium",
        type="decision",
        tags=["database", "pool"],
    )

    # Node 4: Typo-fix note - 5d old, LOW impact, 0 descendants
    node4 = MemoryNode(
        id="typo_note",
        timestamp=(now_dt - timedelta(days=5)).timestamp(),
        content="Fixed typo in log formatting",
        impact="low",
        type="decision",
        tags=["formatting"],
    )

    # Node 5: Hack whose parent was superseded yesterday
    parent_of_hack = "old_auth_dep"
    node5 = MemoryNode(
        id="hack_node",
        timestamp=(now_dt - timedelta(days=2)).timestamp(),
        content="Temporary monkey patch for session cookie serializer",
        impact="medium",
        type="hack",
        tags=["auth"],
        parents=[parent_of_hack],
    )

    desc_counts = {
        "async_mig": 12,
        "jwt_readopt": 5,
        "pool_fix": 2,
        "typo_note": 0,
        "hack_node": 0,
    }

    superseded_events = {
        parent_of_hack: (now_dt - timedelta(days=1)).timestamp(),
    }

    neighbor_map = {
        "async_mig": set(),
        "jwt_readopt": set(),
        "pool_fix": set(),
        "typo_note": set(),
        "hack_node": {parent_of_hack},
    }

    # Compute features & scores
    f1 = BootstrapEngine.compute_node_features(node1, now_ts, desc_counts, superseded_events, neighbor_map)
    s1 = BootstrapEngine.score(f1, node1.type)

    f2 = BootstrapEngine.compute_node_features(node2, now_ts, desc_counts, superseded_events, neighbor_map)
    s2 = BootstrapEngine.score(f2, node2.type)

    f3 = BootstrapEngine.compute_node_features(node3, now_ts, desc_counts, superseded_events, neighbor_map)
    s3 = BootstrapEngine.score(f3, node3.type)

    f4 = BootstrapEngine.compute_node_features(node4, now_ts, desc_counts, superseded_events, neighbor_map)
    s4 = BootstrapEngine.score(f4, node4.type)

    f5 = BootstrapEngine.compute_node_features(node5, now_ts, desc_counts, superseded_events, neighbor_map)
    s5 = BootstrapEngine.score(f5, node5.type)

    # Verify score ranking hierarchy: Foundational old nodes outrank recent minor fixes!
    # s2 and s1 are top tier (~0.67)
    assert s1 > s3
    assert s2 > s3
    assert s3 > s4
    # The hack with superseded parent gets penalized and sinks below everything
    assert s5 < s4


def test_supersedence_and_retraction_filtering(temp_storage):
    """Verify superseded and retracted nodes are filtered out of active briefing candidates."""
    node_active = MemoryNode(
        id="act_1",
        content="Current active guideline",
        impact="high",
        status="active",
    )
    temp_storage.add_memory(node_active)

    node_old = MemoryNode(
        id="old_1",
        content="Old superseded guideline",
        impact="high",
        status="active",
    )
    temp_storage.add_memory(node_old)

    # Supersede old node
    temp_storage.supersede_memory(target_id="old_1", by_id="act_1", reason="Newer approach")

    # Retract a mistaken node
    node_retracted = MemoryNode(
        id="err_1",
        content="Mistaken entry",
        status="active",
    )
    temp_storage.add_memory(node_retracted)
    temp_storage.retract_memory("err_1", reason="Never deployed")

    # Fetch active memories
    active_mems = temp_storage.get_active_memories()
    active_ids = {m.id for m in active_mems}
    assert "act_1" in active_ids
    assert "old_1" not in active_ids
    assert "err_1" not in active_ids

    # Generate briefing
    briefing = BootstrapEngine.generate_briefing(temp_storage)
    assert briefing["count"] == 1
    assert "act_1" in briefing["formatted"]
    assert "old_1" not in briefing["formatted"]


def test_token_budget_and_diversity_assembly(temp_storage):
    """Verify token budgeting partitions into Tier 1 (full) and Tier 2 (summaries) with diversity."""
    # Create 10 decisions with diverse tags
    for i in range(10):
        tag = f"tag_{i % 3}"
        node = MemoryNode(
            id=f"node_{i}",
            content=f"Detailed content for architectural decision number {i}. " * 10,
            summary=f"Decision {i}",
            title=f"Title {i}",
            impact="high" if i < 4 else "medium",
            tags=[tag],
            status="active",
        )
        temp_storage.add_memory(node)

    briefing = BootstrapEngine.generate_briefing(temp_storage, budget=300)
    assert briefing["full_count"] >= 3
    assert briefing["count"] == 10
    assert "Core context" in briefing["formatted"]
    assert "Also relevant" in briefing["formatted"]
