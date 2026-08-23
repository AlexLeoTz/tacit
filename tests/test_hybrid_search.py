"""Unit tests for Hybrid Search, Vector Normalization, and RRF Fusion."""

import math
from pathlib import Path
import tempfile
import pytest

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.search.embeddings import EmbeddingService, QUERY_PREFIX
from src.search.vectordb import normalize, serialize_f32, deserialize_f32
from src.search.hybrid import clean_query, rrf, build_embed_text


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / ".tacit" / "memory.db"
        storage = MemoryStorage(db_path)
        yield storage


def test_vector_normalization_and_serialization():
    v = [1.0, 2.0, 3.0, 4.0]
    norm_v = normalize(v)
    length = math.sqrt(sum(x * x for x in norm_v))
    assert abs(length - 1.0) < 1e-5

    blob = serialize_f32(norm_v)
    assert len(blob) == len(norm_v) * 4
    recovered = deserialize_f32(blob)
    assert len(recovered) == len(norm_v)
    for a, b in zip(norm_v, recovered):
        assert abs(a - b) < 1e-5


def test_clean_query():
    assert clean_query("Search for JWT token renewal?") == "JWT token renewal"
    assert clean_query("why did we increase the database pool size?") == "increase the database pool size"
    assert clean_query("how do we deploy to production?") == "deploy to production"


def test_build_embed_text():
    text = build_embed_text(
        title="FastAPI Migration",
        tags=["fastapi", "async"],
        summary="Switched backend to FastAPI",
        content="Detailed rationale for asynchronous request pipelines.",
    )
    assert "FastAPI Migration" in text
    assert "Tags: fastapi, async" in text
    assert "Detailed rationale" in text


def test_rrf_fusion_logic():
    rankings = [
        ["node_a", "node_b", "node_c"],
        ["node_b", "node_a", "node_d"],
    ]
    scores = rrf(rankings, k=60)
    # node_a: 1/(60+1) + 1/(60+2) = 1/61 + 1/62 ≈ 0.01639 + 0.01613 = 0.03252
    # node_b: 1/(60+2) + 1/(60+1) = 0.03252
    # node_c: 1/(60+3) = 1/63 ≈ 0.01587
    assert scores["node_a"] > scores["node_c"]
    assert scores["node_b"] > scores["node_d"]
    assert abs(scores["node_a"] - scores["node_b"]) < 1e-6


def test_hybrid_search_end_to_end(temp_storage):
    node1 = MemoryNode(
        id="db_pool_node",
        title="Connection Pool Configuration",
        summary="Increased PostgreSQL connection pool limit to 30",
        content="Resolved connection exhaustion under peak traffic by tuning pool size.",
        type="decision",
        tags=["database", "postgres", "pool"],
        scope=["src/db/session.py"],
        impact="high",
        status="active",
    )
    temp_storage.add_memory(node1)

    node2 = MemoryNode(
        id="auth_jwt_node",
        title="JWT Rotation Policy",
        summary="Configured 15-minute refresh rotation for JWT bearer tokens",
        content="Enhanced API authentication security with rotating refresh credentials.",
        type="decision",
        tags=["auth", "jwt", "security"],
        scope=["src/api/auth.py"],
        impact="high",
        status="active",
    )
    temp_storage.add_memory(node2)

    # Search keyword + semantic
    res = temp_storage.search_hybrid("database connection exhaustion", limit=5)
    assert len(res) >= 1
    assert res[0]["node"].id == "db_pool_node"

    # Search with scope hint
    res_scoped = temp_storage.search_hybrid("security", scope_hint=["src/api/auth.py"], limit=5)
    assert len(res_scoped) >= 1
    assert res_scoped[0]["node"].id == "auth_jwt_node"


def test_reindex_all_backfill(temp_storage):
    # Add memory with embedding intentionally cleared
    node = MemoryNode(
        id="unindexed_node",
        title="Celery Worker Setup",
        summary="Configured gevent pool for background tasks",
        content="Running celery with gevent concurrency worker pool.",
        type="command",
        tags=["celery", "worker"],
        status="active",
    )
    temp_storage.add_memory(node)

    # Manually reset embedded_at to test reindex backfill
    conn = temp_storage._get_connection()
    conn.execute("UPDATE memories SET embedding = NULL, embedded_at = NULL WHERE id = 'unindexed_node'")
    conn.commit()
    conn.close()

    done, total = temp_storage.reindex_all(progress=False)
    assert total >= 1
    assert done >= 1

    # Verify embedding was populated
    conn = temp_storage._get_connection()
    row = conn.execute("SELECT embedding, embedded_at FROM memories WHERE id = 'unindexed_node'").fetchone()
    conn.close()
    assert row[0] is not None
    assert row[1] is not None
