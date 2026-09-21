"""Unit tests for the Bootstrap Scoring and Briefing Algorithm."""

from datetime import datetime, timezone, timedelta
import pytest
from pathlib import Path
import tempfile

from src.core.bootstrap import (
    BootstrapEngine,
    Features,
    ScoredNode,
    IMPACT_SCORES,
    IMPACT_FLOOR,
    RECENCY_FLOOR,
    RECENCY_HALF_LIFE_DAYS,
    PENALTY_MAX,
    PENALTY_HALF_LIFE_DAYS,
    estimate_tokens,
    dominant_tag,
    parse_timeframe,
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
    """Authority leads; impact and recency may only reorder within its shadow.

    Expected hierarchy: the foundational decision beats a recent medium fix,
    which beats a recent low-impact note, and a memory whose parent was just
    superseded is pushed down.
    """
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

    # PageRank authority: what the graph says about each memory's importance.
    authority = {
        "async_mig": 1.00,    # the foundation everything else traces back to
        "jwt_readopt": 0.55,
        "pool_fix": 0.30,
        "typo_note": 0.05,    # leaf, nothing built on it
        "hack_node": 0.12,    # leaf
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
    f1 = BootstrapEngine.compute_node_features(node1, now_ts, authority["async_mig"], superseded_events, neighbor_map)
    s1 = BootstrapEngine.score(f1, node1.type)

    f2 = BootstrapEngine.compute_node_features(node2, now_ts, authority["jwt_readopt"], superseded_events, neighbor_map)
    s2 = BootstrapEngine.score(f2, node2.type)

    f3 = BootstrapEngine.compute_node_features(node3, now_ts, authority["pool_fix"], superseded_events, neighbor_map)
    s3 = BootstrapEngine.score(f3, node3.type)

    f4 = BootstrapEngine.compute_node_features(node4, now_ts, authority["typo_note"], superseded_events, neighbor_map)
    s4 = BootstrapEngine.score(f4, node4.type)

    f5 = BootstrapEngine.compute_node_features(node5, now_ts, authority["hack_node"], superseded_events, neighbor_map)
    s5 = BootstrapEngine.score(f5, node5.type)

    # Verify the score ranking hierarchy: high-authority foundations outrank
    # recent minor fixes, and a memory next to a fresh supersede sinks.
    assert f1.authority == 1.0
    assert s1 > s2 > s3 > s4
    # The hack whose parent was superseded yesterday is pushed below everything
    assert s5 < s4


def test_impact_and_recency_cannot_overturn_a_large_authority_gap():
    """The whole point of authority-first scoring: bounded tie-breakers."""
    now_ts = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc).timestamp()
    fresh_low_impact = MemoryNode(
        id="fresh", content="recent minor note", impact="low", timestamp=now_ts
    )
    old_high_impact = MemoryNode(
        id="old", content="foundational", impact="high",
        timestamp=now_ts - 365 * 86400,
    )

    best_case_challenger = BootstrapEngine.score(
        BootstrapEngine.compute_node_features(fresh_low_impact, now_ts, 0.2, {}, {}),
        fresh_low_impact.type,
    )
    worst_case_foundation = BootstrapEngine.score(
        BootstrapEngine.compute_node_features(old_high_impact, now_ts, 1.0, {}, {}),
        old_high_impact.type,
    )

    assert worst_case_foundation > best_case_challenger


def test_multipliers_are_bounded_by_their_floors():
    """The tie-breakers discount a memory but can never erase its authority."""
    node = MemoryNode(id="n", content="c", impact="low")
    ten_years_on = node.timestamp + 3650 * 86400
    features = BootstrapEngine.compute_node_features(node, ten_years_on, 1.0, {}, {})
    score = BootstrapEngine.score(features, "decision")

    worst_impact_multiplier = IMPACT_FLOOR + (1.0 - IMPACT_FLOOR) * IMPACT_SCORES["low"]
    assert features.recency < 0.001
    assert score == pytest.approx(worst_impact_multiplier * RECENCY_FLOOR, rel=1e-3)
    assert score > 0.5, "an old, low-impact memory keeps roughly half its authority"


def test_parse_timeframe_accepts_names_suffixes_and_dates():
    now_ts = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc).timestamp()

    assert parse_timeframe("all", now_ts) is None
    assert parse_timeframe(None, now_ts) is None
    assert parse_timeframe("", now_ts) is None
    assert parse_timeframe("nonsense", now_ts) is None, "bad input must not break bootstrapping"

    week = parse_timeframe("week", now_ts)
    assert now_ts - week == pytest.approx(7 * 86400, rel=1e-6)

    assert now_ts - parse_timeframe("30d", now_ts) == pytest.approx(30 * 86400, rel=1e-6)
    assert now_ts - parse_timeframe("6h", now_ts) == pytest.approx(6 * 3600, rel=1e-6)
    assert now_ts - parse_timeframe("2w", now_ts) == pytest.approx(14 * 86400, rel=1e-6)

    cutoff = parse_timeframe("2026-08-01", now_ts)
    assert datetime.fromtimestamp(cutoff, timezone.utc).date().isoformat() == "2026-08-01"


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
