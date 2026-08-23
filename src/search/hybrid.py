"""Hybrid Search combining SQLite FTS5 (BM25) and dense embeddings via Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .embeddings import EmbeddingService
from .vectordb import deserialize_f32, normalize, serialize_f32

RRF_K = 60
RETRIEVE_K = 50
SCOPE_BOOST = 0.5
RECENCY_HALF_LIFE_DAYS = 90

LEADINS = [
    "search for",
    "find memories about",
    "memories about",
    "look up",
    "remember",
    "find",
    "what is",
    "how do we",
    "why did we",
]


def build_embed_text(
    title: Optional[str] = "",
    tags: Optional[Sequence[str]] = None,
    summary: Optional[str] = "",
    content: Optional[str] = "",
    max_chars: int = 2000,
) -> str:
    """Compose structured text for document embedding. Tags bridge keyword and conceptual search."""
    parts = []
    if title:
        parts.append(title.strip())
    if tags:
        clean_tags = [t.strip() for t in tags if t.strip()]
        if clean_tags:
            parts.append(f"Tags: {', '.join(clean_tags)}")
    if summary:
        parts.append(summary.strip())
    if content:
        parts.append(content.strip()[:max_chars])
    return "\n".join(parts)


def clean_query(q: str) -> str:
    """Strip question boilerplate and search lead-ins from agent-authored queries."""
    q = q.strip().strip("?").strip()
    low = q.lower()
    for lead in LEADINS:
        if low.startswith(lead):
            q = q[len(lead):].strip(" :,-")
            break
    return q


def bm25_search(
    conn,
    query: str,
    k: int = RETRIEVE_K,
    type_filter: Optional[str] = None,
    tags: Optional[List[str]] = None,
    include_superseded: bool = False,
) -> List[str]:
    """Channel A: Fast-text keyword matching using SQLite FTS5 / BM25 ranking."""
    if not query.strip():
        return []

    # Clean and sanitize tokens for FTS5 syntax
    sanitized = "".join(c if c.isalnum() or c.isspace() else " " for c in query).strip()
    if not sanitized:
        return []
    fts_query = f"{sanitized}*"

    status_condition = "status IN ('active', 'superseded')" if include_superseded else "status = 'active'"

    conditions = [f"m.{status_condition}"]
    params: List[Any] = [fts_query]

    if type_filter:
        conditions.append("m.type = ?")
        params.append(type_filter)

    where_clause = " AND ".join(conditions)
    params.append(k)

    sql = f"""
        SELECT m.id FROM memories m
        JOIN memories_fts f ON m.id = f.memory_id
        WHERE memories_fts MATCH ? AND {where_clause}
        ORDER BY bm25(memories_fts) ASC
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, params).fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        # Fallback LIKE search if FTS table uninitialized or matches syntax error
        like_term = f"%{query}%"
        fallback_sql = f"""
            SELECT id FROM memories
            WHERE (content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?)
              AND {status_condition}
            ORDER BY timestamp DESC LIMIT ?
        """
        rows = conn.execute(fallback_sql, (like_term, like_term, like_term, like_term, k)).fetchall()
        return [str(r[0]) for r in rows]


def vector_search(
    conn,
    query_vec: List[float],
    k: int = RETRIEVE_K,
    type_filter: Optional[str] = None,
    include_superseded: bool = False,
) -> List[str]:
    """Channel B: Dense embedding vector similarity search with numpy fallback."""
    return _numpy_bruteforce(conn, query_vec, k=k, type_filter=type_filter, include_superseded=include_superseded)


def _numpy_bruteforce(
    conn,
    query_vec: List[float],
    k: int = RETRIEVE_K,
    type_filter: Optional[str] = None,
    include_superseded: bool = False,
) -> List[str]:
    """Brute-force dot-product similarity over L2-normalized float32 BLOB vectors."""
    try:
        import numpy as np
    except ImportError:
        return []

    status_condition = "status IN ('active', 'superseded')" if include_superseded else "status = 'active'"
    conditions = [status_condition, "embedding IS NOT NULL"]
    params: List[Any] = []

    if type_filter:
        conditions.append("type = ?")
        params.append(type_filter)

    where_clause = " AND ".join(conditions)
    sql = f"SELECT id, embedding FROM memories WHERE {where_clause}"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []

    node_ids = [str(r[0]) for r in rows]
    blob_bytes = b"".join(r[1] for r in rows)
    num_nodes = len(rows)
    embed_dim = len(query_vec)

    try:
        mat = np.frombuffer(blob_bytes, dtype=np.float32).reshape(num_nodes, embed_dim)
        q = np.asarray(query_vec, dtype=np.float32)
        # Cosine similarity equals dot product for L2-normalized vectors
        sims = mat @ q
        sorted_indices = np.argsort(-sims)
        # Filter by minimum similarity threshold to avoid noise in small or disjoint corpora
        matched_indices = [int(i) for i in sorted_indices if float(sims[i]) >= 0.52][:k]
        return [node_ids[i] for i in matched_indices]
    except Exception:
        return []


def rrf(rankings: List[List[str]], k: int = RRF_K) -> Dict[str, float]:
    """Reciprocal Rank Fusion: merge multiple ranked lists into a calibrated score."""
    scores: Dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, node_id in enumerate(ranking, start=1):
            scores[node_id] += 1.0 / (k + rank)
    return dict(scores)


def apply_boosts(
    conn,
    fused: Dict[str, float],
    scope_hint: Optional[List[str]] = None,
    now_ts: Optional[float] = None,
) -> List[Tuple[str, float]]:
    """Apply scope-matching and recency decay multipliers to fused RRF scores."""
    if not fused:
        return []

    now_ts = now_ts or datetime.now(timezone.utc).timestamp()
    node_ids = list(fused.keys())

    placeholders = ",".join("?" for _ in node_ids)
    sql = f"SELECT id, timestamp, scope FROM memories WHERE id IN ({placeholders})"
    rows = conn.execute(sql, node_ids).fetchall()
    meta = {str(r[0]): (float(r[1]), str(r[2])) for r in rows}

    boosted: List[Tuple[str, float]] = []
    for node_id, rrf_score in fused.items():
        mult = 1.0
        ts, scope_json = meta.get(node_id, (now_ts, "[]"))

        # Multiplicative scope boost
        if scope_hint and scope_json:
            clean_scope = scope_json.lower()
            if any(h.lower() in clean_scope for h in scope_hint if h.strip()):
                mult *= (1.0 + SCOPE_BOOST)

        # Gentle recency half-life decay (90 days)
        age_days = max(0.0, (now_ts - ts) / 86400.0)
        mult *= math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS)

        boosted.append((node_id, rrf_score * mult))

    # Sort descending by score, tie-break by node_id
    boosted.sort(key=lambda item: (-item[1], item[0]))
    return boosted


class HybridSearchEngine:
    """Coordinates BM25, ONNX dense vector retrieval, and RRF fusion."""

    @classmethod
    def search(
        cls,
        conn,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
        scope_hint: Optional[List[str]] = None,
        type_filter: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_superseded: bool = False,
        now_dt: Optional[datetime] = None,
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search returning ranked node dictionaries."""
        q = clean_query(query)
        now_ts = (now_dt or datetime.now(timezone.utc)).timestamp()

        # Handle empty/degenerate query
        if not q:
            status_clause = "status IN ('active', 'superseded')" if include_superseded else "status = 'active'"
            sql = f"SELECT * FROM memories WHERE {status_clause} ORDER BY timestamp DESC LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
            from ..core.memory_node import MemoryNode
            return [{"node": MemoryNode.from_dict(dict(r)), "score": 1.0, "provenance": {"mode": "recent"}} for r in rows]

        embed_svc = EmbeddingService.get()
        use_vectors = (mode == "hybrid" and embed_svc.available)

        bm25_ranked = bm25_search(
            conn=conn,
            query=q,
            k=RETRIEVE_K,
            type_filter=type_filter,
            tags=tags,
            include_superseded=include_superseded,
        )

        vec_ranked: List[str] = []
        if use_vectors:
            try:
                raw_qvec = embed_svc.embed_query(q)
                norm_qvec = normalize(raw_qvec)
                vec_ranked = vector_search(
                    conn=conn,
                    query_vec=norm_qvec,
                    k=RETRIEVE_K,
                    type_filter=type_filter,
                    include_superseded=include_superseded,
                )
            except Exception:
                vec_ranked = []

        rankings = [bm25_ranked]
        if vec_ranked:
            rankings.append(vec_ranked)

        fused = rrf(rankings)
        boosted_pairs = apply_boosts(conn, fused, scope_hint=scope_hint, now_ts=now_ts)[:limit]

        # Fetch full nodes
        if not boosted_pairs:
            return []

        from ..core.memory_node import MemoryNode
        results = []
        for node_id, final_score in boosted_pairs:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (node_id,)).fetchone()
            if row:
                node = MemoryNode.from_dict(dict(row))
                item: Dict[str, Any] = {
                    "node": node,
                    "score": final_score,
                }
                if debug:
                    bm25_idx = bm25_ranked.index(node_id) + 1 if node_id in bm25_ranked else None
                    vec_idx = vec_ranked.index(node_id) + 1 if node_id in vec_ranked else None
                    item["provenance"] = {
                        "mode": "hybrid" if vec_ranked else "keyword-only",
                        "bm25_rank": bm25_idx,
                        "vec_rank": vec_idx,
                    }
                results.append(item)

        return results
