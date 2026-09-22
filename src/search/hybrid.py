"""Hybrid Search combining SQLite FTS5 (BM25) and dense embeddings via Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .embeddings import EmbeddingService
from .vectordb import deserialize_f32, normalize, serialize_f32
from ..utils.config import Config
from ..utils.scope import node_matches_scope

RRF_K = 60
RETRIEVE_K = 50
RECENCY_HALF_LIFE_DAYS = 90

#: How much authority may swing a result, as a multiplier floor. Scores are
#: ``relevance * (AUTHORITY_FLOOR + (1 - AUTHORITY_FLOOR) * authority)``, so a
#: foundational memory can at most double its relevance while an obscure one can
#: be halved — authority modulates relevance instead of overriding it, which is
#: what keeps a highly-cited but off-topic memory out of the results.
AUTHORITY_FLOOR = 0.5

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
) -> str:
    """Compose the text that represents a memory in the vector index.

    Only the title, tags and summary are embedded — never the full content. This
    keeps a write cheap (~30-60 tokens instead of ~500) and produces a sharper
    vector, at the cost of making title and summary quality load-bearing. That is
    why the agent rules require a specific, descriptive title on every entry.

    Tags are included deliberately: they bridge keyword and conceptual search.
    """
    parts = []
    if title:
        parts.append(title.strip())
    if tags:
        clean_tags = [t.strip() for t in tags if t.strip()]
        if clean_tags:
            parts.append(f"Tags: {', '.join(clean_tags)}")
    if summary:
        parts.append(summary.strip())
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
    embed_dim = len(query_vec)
    expected_bytes = embed_dim * 4

    # Vectors from a different embedding model cannot be compared with this
    # query. Keep only the rows matching the current dimension: without this,
    # switching provider (384 -> 768 -> 1536) makes the reshape below throw and
    # semantic search silently degrades to nothing at all.
    usable = [(str(r[0]), r[1]) for r in rows if r[1] and len(r[1]) == expected_bytes]
    if not usable:
        return []

    node_ids = [node_id for node_id, _ in usable]
    blob_bytes = b"".join(blob for _, blob in usable)
    num_nodes = len(usable)

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


def authority_scores(conn) -> Dict[str, float]:
    """PageRank authority for every active memory, keyed by node id.

    Reads only ``id`` and ``parents`` so the whole project can be scored without
    materialising ``MemoryNode`` objects for rows that will never be returned.
    """
    from ..core.authority import compute_authority_from_pairs

    try:
        rows = conn.execute(
            "SELECT id, parents FROM memories WHERE status = 'active' OR status IS NULL"
        ).fetchall()
    except Exception:
        return {}

    pairs = []
    for row in rows:
        raw = row[1]
        try:
            parents = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            parents = []
        pairs.append((str(row[0]), parents if isinstance(parents, list) else []))

    try:
        edges = [dict(edge) for edge in conn.execute("SELECT * FROM edges").fetchall()]
    except Exception:
        edges = []

    return compute_authority_from_pairs(pairs, edges)


def apply_boosts(
    conn,
    fused: Dict[str, float],
    scope_hint: Optional[List[str]] = None,
    now_ts: Optional[float] = None,
    authority: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float]]:
    """Apply scope filtering and recency/authority multipliers to fused RRF scores.

    Scope is a FILTER here, matching the briefing: when the caller names the files
    or directories it is working in, only memories scoped to them (plus
    project-wide knowledge) are ranked. Scoring then applies recency and
    PageRank authority.
    """
    if not fused:
        return []

    now_ts = now_ts or datetime.now(timezone.utc).timestamp()
    node_ids = list(fused.keys())

    placeholders = ",".join("?" for _ in node_ids)
    sql = f"SELECT id, timestamp, scope FROM memories WHERE id IN ({placeholders})"
    rows = conn.execute(sql, node_ids).fetchall()
    meta = {str(r[0]): (float(r[1]), str(r[2])) for r in rows}

    project_root: Optional[Path] = None
    try:
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        if db_path:
            project_root = Config.project_root_for_db(db_path)
    except Exception:
        project_root = None

    boosted: List[Tuple[str, float]] = []
    for node_id, rrf_score in fused.items():
        mult = 1.0
        ts, scope_json = meta.get(node_id, (now_ts, "[]"))

        if scope_hint:
            try:
                node_scope = json.loads(scope_json) if scope_json else []
            except (TypeError, ValueError):
                node_scope = []
            if not node_matches_scope(
                node_scope if isinstance(node_scope, list) else [],
                scope_hint,
                project_root=project_root,
            ):
                continue

        # Gentle recency half-life decay (90 days)
        age_days = max(0.0, (now_ts - ts) / 86400.0)
        mult *= math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS)

        # Authority: relevance says "about the query", PageRank says "worth
        # reading". Neither can rescue the other.
        if authority:
            node_authority = authority.get(node_id, 0.0)
            mult *= AUTHORITY_FLOOR + (1.0 - AUTHORITY_FLOOR) * node_authority

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
            rows = conn.execute(sql, (limit if not scope_hint else RETRIEVE_K,)).fetchall()
            from ..core.memory_node import MemoryNode
            recent = [MemoryNode.from_dict(dict(r)) for r in rows]
            if scope_hint:
                # An empty query is still a scoped read: filter before truncating.
                project_root: Optional[Path] = None
                try:
                    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
                    if db_path:
                        project_root = Config.project_root_for_db(db_path)
                except Exception:
                    project_root = None
                recent = [
                    node for node in recent
                    if node_matches_scope(node.scope or [], scope_hint, project_root=project_root)
                ][:limit]
            return [{"node": node, "score": 1.0, "provenance": {"mode": "recent"}} for node in recent]

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
        authority = authority_scores(conn) if fused else {}
        boosted_pairs = apply_boosts(
            conn, fused, scope_hint=scope_hint, now_ts=now_ts, authority=authority
        )[:limit]

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
