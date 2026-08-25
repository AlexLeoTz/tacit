"""SQLite-based storage layer with full-text search index for Tacit."""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading

from .memory_node import MemoryNode


class MemoryStorage:
    """Thread-safe SQLite storage with FTS5 full-text indexing."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fts_available = True
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with row factory configured."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema, indexes, and full-text search table."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        timestamp REAL,
                        content TEXT,
                        summary TEXT,
                        title TEXT,
                        type TEXT,
                        tags TEXT,
                        scope TEXT,
                        impact TEXT,
                        parents TEXT,
                        children TEXT,
                        related TEXT,
                        author TEXT,
                        model_version TEXT,
                        status TEXT,
                        content_hash TEXT UNIQUE,
                        merkle_root TEXT,
                        metadata TEXT,
                        embedding BLOB,
                        embedded_at REAL
                    )
                """)

                # Automatic schema migration for existing databases
                try:
                    conn.execute("ALTER TABLE memories ADD COLUMN embedding BLOB")
                except Exception:
                    pass
                try:
                    conn.execute("ALTER TABLE memories ADD COLUMN embedded_at REAL")
                except Exception:
                    pass

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS edges (
                        child_id TEXT NOT NULL,
                        parent_id TEXT NOT NULL,
                        relation TEXT NOT NULL DEFAULT 'derives_from',
                        reason TEXT,
                        created_at REAL NOT NULL,
                        created_by TEXT NOT NULL DEFAULT 'agent',
                        PRIMARY KEY (child_id, parent_id, relation)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lifecycle_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_id TEXT NOT NULL,
                        event TEXT NOT NULL,
                        actor TEXT NOT NULL DEFAULT 'agent',
                        reason TEXT,
                        at REAL NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_timestamp 
                    ON memories(timestamp)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_type 
                    ON memories(type)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_status 
                    ON memories(status)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_content_hash
                    ON memories(content_hash)
                """)

                try:
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts 
                        USING fts5(
                            memory_id UNINDEXED,
                            content, 
                            summary, 
                            title,
                            tags
                        )
                    """)
                    self._fts_available = True
                except sqlite3.OperationalError:
                    self._fts_available = False

                conn.commit()
            finally:
                conn.close()

    def _write_markdown_file(self, node: MemoryNode) -> None:
        """Write an individual memory node as a formatted markdown file in its category directory."""
        try:
            import re
            from datetime import datetime
            from ..export.templates import MEMORY_MARKDOWN_TEMPLATE

            category_dir = self.db_path.parent / node.type
            category_dir.mkdir(parents=True, exist_ok=True)

            date_prefix = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d")
            slug = re.sub(r"[^\w\s-]", "", node.title or node.summary).strip().lower()
            slug = re.sub(r"[-\s]+", "-", slug)[:50] or "memory"
            filename = f"{date_prefix}_{slug}_{node.id[:8]}.md"
            file_path = category_dir / filename

            date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            md_content = MEMORY_MARKDOWN_TEMPLATE.format(
                title=node.title or node.summary,
                id=node.id,
                type=node.type,
                date=date_str,
                impact=node.impact,
                status=node.status,
                author=node.author,
                summary=node.summary,
                content=node.content,
                tags=", ".join(node.tags) if node.tags else "None",
                scope=", ".join(node.scope) if node.scope else "Global",
                parents=", ".join(f"`{p}`" for p in node.parents) if node.parents else "None",
                children=", ".join(f"`{c}`" for c in node.children) if node.children else "None",
                related=", ".join(f"`{r}`" for r in node.related) if node.related else "None",
                content_hash=node.content_hash,
                merkle_root=node.merkle_root,
            )
            file_path.write_text(md_content, encoding="utf-8")
        except Exception as e:
            # Fallback direct write if anything fails
            try:
                cat_dir = self.db_path.parent / (node.type or "context")
                cat_dir.mkdir(parents=True, exist_ok=True)
                (cat_dir / f"{node.id[:8]}.md").write_text(f"# {node.title or node.summary}\n\n{node.content}", encoding="utf-8")
            except Exception:
                pass

    def _delete_markdown_file(self, node_id: str, memory_type: Optional[str] = None) -> None:
        """Delete markdown file corresponding to node_id from category directory."""
        try:
            target_dirs = [self.db_path.parent / memory_type] if memory_type else [
                self.db_path.parent / t for t in ("decision", "architecture", "hack", "command", "error", "context")
            ]
            for cat_dir in target_dirs:
                if cat_dir.exists():
                    for md_file in cat_dir.glob(f"*_{node_id[:8]}.md"):
                        try:
                            md_file.unlink()
                        except Exception:
                            pass
        except Exception:
            pass

    def add_memory(
        self,
        node: MemoryNode,
        supersedes: Optional[List[str]] = None,
        relation_reason: Optional[str] = None,
    ) -> bool:
        """Add memory node to SQLite database, update FTS index, record edges, handle supersedence, and write markdown file."""
        with self._lock:
            conn = self._get_connection()
            try:
                data = node.to_dict()
                conn.execute("""
                    INSERT INTO memories (
                        id, timestamp, content, summary, title,
                        type, tags, scope, impact, parents,
                        children, related, author, model_version,
                        status, content_hash, merkle_root, metadata
                    ) VALUES (
                        :id, :timestamp, :content, :summary, :title,
                        :type, :tags, :scope, :impact, :parents,
                        :children, :related, :author, :model_version,
                        :status, :content_hash, :merkle_root, :metadata
                    )
                """, data)

                # Record derives_from edges
                for p_id in node.parents:
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO edges (child_id, parent_id, relation, reason, created_at, created_by)
                            VALUES (?, ?, 'derives_from', ?, ?, ?)
                        """, (node.id, p_id, relation_reason, node.timestamp, node.author))
                    except Exception:
                        pass

                # Record created lifecycle event
                try:
                    conn.execute("""
                        INSERT INTO lifecycle_events (node_id, event, actor, reason, at)
                        VALUES (?, 'created', ?, ?, ?)
                    """, (node.id, node.author, f"Node created: {node.summary}", node.timestamp))
                except Exception:
                    pass

                # Handle explicit supersedes
                if supersedes:
                    for sup_id in supersedes:
                        # Flip target memory status to superseded
                        conn.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (sup_id,))
                        # Insert supersedes edge
                        try:
                            conn.execute("""
                                INSERT OR REPLACE INTO edges (child_id, parent_id, relation, reason, created_at, created_by)
                                VALUES (?, ?, 'supersedes', ?, ?, ?)
                            """, (node.id, sup_id, relation_reason, node.timestamp, node.author))
                        except Exception:
                            pass
                        # Log lifecycle event
                        try:
                            conn.execute("""
                                INSERT INTO lifecycle_events (node_id, event, actor, reason, at)
                                VALUES (?, 'superseded', ?, ?, ?)
                            """, (sup_id, node.author, relation_reason or f"Superseded by {node.id}", node.timestamp))
                        except Exception:
                            pass

                if self._fts_available:
                    tags_str = " ".join(node.tags)
                    conn.execute("""
                        INSERT INTO memories_fts(memory_id, content, summary, title, tags)
                        VALUES (?, ?, ?, ?, ?)
                    """, (node.id, node.content, node.summary, node.title, tags_str))

                # Write-path embedding (never fails the add)
                try:
                    from ..search.embeddings import EmbeddingService
                    from ..search.hybrid import build_embed_text
                    from ..search.vectordb import normalize, serialize_f32
                    embed_svc = EmbeddingService.get()
                    if embed_svc.available:
                        text = build_embed_text(title=node.title, tags=node.tags, summary=node.summary, content=node.content)
                        raw_vec = embed_svc.embed_documents([text])[0]
                        norm_vec = normalize(raw_vec)
                        blob = serialize_f32(norm_vec)
                        conn.execute("UPDATE memories SET embedding = ?, embedded_at = ? WHERE id = ?", (blob, node.timestamp, node.id))
                except Exception:
                    pass

                conn.commit()
                # Dual-write: write markdown file immediately to category directory if enabled
                from ..utils.config import Config
                if Config.DUAL_WRITE:
                    self._write_markdown_file(node)
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def get_memory(self, node_id: str) -> Optional[MemoryNode]:
        """Retrieve memory by its ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT * FROM memories WHERE id = ?", (node_id,)).fetchone()
                if row:
                    return MemoryNode.from_dict(dict(row))
                return None
            finally:
                conn.close()

    def search_full_text(
        self, query: str, limit: int = 10, memory_type: Optional[str] = None
    ) -> List[MemoryNode]:
        """Perform full-text search matching query keywords using SQLite FTS5."""
        if not query.strip():
            return []

        with self._lock:
            conn = self._get_connection()
            try:
                if self._fts_available:
                    # Clean and sanitize tokens for FTS5 syntax
                    sanitized = "".join(c if c.isalnum() or c.isspace() else " " for c in query).strip()
                    if not sanitized:
                        return []
                    fts_query = f"{sanitized}*"
                    
                    if memory_type:
                        sql = """
                            SELECT m.* FROM memories m
                            JOIN memories_fts f ON m.id = f.memory_id
                            WHERE memories_fts MATCH ? AND m.type = ?
                            ORDER BY bm25(memories_fts)
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (fts_query, memory_type, limit)).fetchall()
                    else:
                        sql = """
                            SELECT m.* FROM memories m
                            JOIN memories_fts f ON m.id = f.memory_id
                            WHERE memories_fts MATCH ?
                            ORDER BY bm25(memories_fts)
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (fts_query, limit)).fetchall()
                else:
                    like_term = f"%{query.strip()}%"
                    if memory_type:
                        sql = """
                            SELECT * FROM memories
                            WHERE (content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?)
                              AND type = ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (like_term, like_term, like_term, like_term, memory_type, limit)).fetchall()
                    else:
                        sql = """
                            SELECT * FROM memories
                            WHERE content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (like_term, like_term, like_term, like_term, limit)).fetchall()

                return [MemoryNode.from_dict(dict(row)) for row in rows]
            finally:
                conn.close()

    def get_all(
        self, limit: int = 100, offset: int = 0, memory_type: Optional[str] = None
    ) -> List[MemoryNode]:
        """Get all memories sorted by timestamp descending with optional pagination."""
        with self._lock:
            conn = self._get_connection()
            try:
                if memory_type:
                    rows = conn.execute("""
                        SELECT * FROM memories 
                        WHERE type = ?
                        ORDER BY timestamp DESC 
                        LIMIT ? OFFSET ?
                    """, (memory_type, limit, offset)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT * FROM memories 
                        ORDER BY timestamp DESC 
                        LIMIT ? OFFSET ?
                    """, (limit, offset)).fetchall()
                return [MemoryNode.from_dict(dict(row)) for row in rows]
            finally:
                conn.close()

    def get_since(self, timestamp: float) -> List[MemoryNode]:
        """Get all memories created after a given timestamp."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("""
                    SELECT * FROM memories 
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                """, (timestamp,)).fetchall()
                return [MemoryNode.from_dict(dict(row)) for row in rows]
            finally:
                conn.close()

    def get_count(self, memory_type: Optional[str] = None) -> int:
        """Get total number of memories stored."""
        with self._lock:
            conn = self._get_connection()
            try:
                if memory_type:
                    row = conn.execute("SELECT COUNT(*) FROM memories WHERE type = ?", (memory_type,)).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

    def delete_memory(self, node_id: str) -> bool:
        """Delete a single memory by ID from memories, FTS index, and markdown files."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM memories WHERE id = ?", (node_id,))
                deleted = cursor.rowcount > 0
                if self._fts_available and deleted:
                    conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (node_id,))
                conn.commit()
                if deleted:
                    self._delete_markdown_file(node_id)
                return deleted
            finally:
                conn.close()

    def get_active_memories(self, limit: int = 1000) -> List[MemoryNode]:
        """Get all active memories (excluding superseded or retracted nodes)."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("""
                    SELECT * FROM memories 
                    WHERE status = 'active' OR status IS NULL
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                return [MemoryNode.from_dict(dict(row)) for row in rows]
            finally:
                conn.close()

    def find_candidate_parents(
        self,
        scope: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        title: str = "",
        summary: str = "",
        content: str = "",
        exclude_ids: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Find ranked candidate parent nodes based on scope overlap, tag similarity, text BM25/FTS, and recency."""
        exclude_set = set(exclude_ids or [])
        scope = [s.strip().replace("\\", "/").lower() for s in (scope or []) if s.strip()]
        tags_set = set(t.strip().lower() for t in (tags or []) if t.strip())

        with self._lock:
            conn = self._get_connection()
            try:
                # Fetch recent active memories as candidate pool
                rows = conn.execute("""
                    SELECT *
                    FROM memories
                    WHERE status = 'active' OR status IS NULL
                    ORDER BY timestamp DESC
                    LIMIT 150
                """).fetchall()

                if not rows:
                    return []

                import json
                candidates = []
                now = rows[0]["timestamp"] if rows else 0

                query_text = f"{title} {summary}".strip().lower()
                query_tokens = set(query_text.split()) if query_text else set()

                def _parse_list(val):
                    if isinstance(val, list):
                        return val
                    if isinstance(val, str):
                        try:
                            res = json.loads(val)
                            if isinstance(res, list):
                                return res
                        except Exception:
                            pass
                    return []

                for r in rows:
                    node_id = r["id"]
                    if node_id in exclude_set:
                        continue

                    r_tags = [str(t).lower() for t in _parse_list(r["tags"])]
                    r_scope = [str(s).replace("\\", "/").lower() for s in _parse_list(r["scope"])]
                    r_title = (r["title"] or "").lower()
                    r_summary = (r["summary"] or "").lower()
                    r_type = r["type"]

                    score = 0.0
                    reasons = []

                    # 1. Scope overlap (Strongest signal: 0.40)
                    if scope and r_scope:
                        scope_match = False
                        for s1 in scope:
                            for s2 in r_scope:
                                if s1 == s2 or s1.startswith(s2) or s2.startswith(s1):
                                    scope_match = True
                                    break
                            if scope_match:
                                break
                        if scope_match:
                            score += 0.40
                            reasons.append("scope overlap")

                    # 2. Tag similarity (Jaccard: 0.30)
                    if tags_set and r_tags:
                        r_tags_set = set(r_tags)
                        inter = tags_set.intersection(r_tags_set)
                        if inter:
                            jaccard = len(inter) / len(tags_set.union(r_tags_set))
                            score += jaccard * 0.30
                            reasons.append(f"shared tags: {', '.join(inter)}")

                    # 3. Text / Keyword overlap in title/summary (0.20)
                    if query_tokens:
                        r_text_tokens = set(f"{r_title} {r_summary}".split())
                        text_inter = query_tokens.intersection(r_text_tokens)
                        if text_inter:
                            overlap_ratio = min(1.0, len(text_inter) / max(1, len(query_tokens)))
                            score += overlap_ratio * 0.20
                            reasons.append("keyword overlap")

                    # 4. Natural Causal Type Affinity (0.10)
                    # e.g., an error is a natural parent for decision/hack
                    if r_type == "error":
                        score += 0.08
                        reasons.append("resolves error")
                    elif r_type in ("architecture", "decision"):
                        score += 0.04

                    # 5. Recency decay bonus (up to 0.10)
                    age_seconds = max(0, now - r["timestamp"])
                    recency_factor = max(0.0, 1.0 - (age_seconds / (14 * 86400)))  # decays over 14 days
                    score += recency_factor * 0.10

                    if score >= 0.15:  # Minimum threshold for relevancy
                        node = MemoryNode(
                            id=node_id,
                            timestamp=float(r["timestamp"]),
                            content=r["content"],
                            summary=r["summary"] or "",
                            title=r["title"] or "",
                            type=r_type,
                            tags=r_tags,
                            scope=r_scope,
                            impact=r["impact"] if "impact" in r.keys() else "medium",
                            parents=_parse_list(r["parents"]) if "parents" in r.keys() else [],
                            author=r["author"] if "author" in r.keys() and r["author"] else "ai-agent",
                            status=r["status"] if "status" in r.keys() and r["status"] else "active",
                        )
                        candidates.append({
                            "node": node,
                            "score": round(score, 3),
                            "reasons": reasons,
                        })

                # Sort by score descending
                candidates.sort(key=lambda c: c["score"], reverse=True)
                return candidates[:limit]
            finally:
                conn.close()

    def link_nodes(
        self,
        child_id: str,
        parent_id: str,
        relation: str = "derives_from",
        reason: Optional[str] = None,
        actor: str = "ai-agent",
    ) -> bool:
        """Add a causal edge between two existing nodes and update child's parents array."""
        with self._lock:
            conn = self._get_connection()
            try:
                # Validate both nodes exist
                child_row = conn.execute("SELECT * FROM memories WHERE id = ?", (child_id,)).fetchone()
                parent_row = conn.execute("SELECT * FROM memories WHERE id = ?", (parent_id,)).fetchone()
                if not child_row or not parent_row:
                    return False

                import json
                import time
                timestamp = time.time()

                # Insert edge
                conn.execute("""
                    INSERT OR REPLACE INTO edges (child_id, parent_id, relation, reason, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (child_id, parent_id, relation, reason, timestamp, actor))

                # Update child parents / supersedes array if needed
                child_parents = json.loads(child_row["parents"] or "[]")
                if relation == "derives_from" and parent_id not in child_parents:
                    child_parents.append(parent_id)
                    conn.execute("UPDATE memories SET parents = ? WHERE id = ?", (json.dumps(child_parents), child_id))

                if relation == "supersedes":
                    conn.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (parent_id,))

                # Record lifecycle event
                conn.execute("""
                    INSERT INTO lifecycle_events (node_id, event, actor, reason, at)
                    VALUES (?, 'linked', ?, ?, ?)
                """, (child_id, actor, f"Linked {relation} -> {parent_id}" + (f" ({reason})" if reason else ""), timestamp))

                conn.commit()
                return True
            except Exception:
                return False
            finally:
                conn.close()

    def get_edges(self) -> List[Dict[str, Any]]:
        """Get all relational graph edges."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("SELECT * FROM edges").fetchall()
                return [dict(row) for row in rows]
            except Exception:
                return []
            finally:
                conn.close()

    def get_lifecycle_events(self, node_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get lifecycle history events for a node or entire project."""
        with self._lock:
            conn = self._get_connection()
            try:
                if node_id:
                    rows = conn.execute(
                        "SELECT * FROM lifecycle_events WHERE node_id = ? ORDER BY at ASC",
                        (node_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM lifecycle_events ORDER BY at ASC"
                    ).fetchall()
                return [dict(row) for row in rows]
            except Exception:
                return []
            finally:
                conn.close()

    def retract_memory(self, node_id: str, reason: str = "", actor: str = "human") -> bool:
        """Mark a memory node as retracted (erroneous/invalidated) while preserving audit trail."""
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("UPDATE memories SET status = 'retracted' WHERE id = ?", (node_id,))
                if cursor.rowcount > 0:
                    try:
                        conn.execute("""
                            INSERT INTO lifecycle_events (node_id, event, actor, reason, at)
                            VALUES (?, 'retracted', ?, ?, ?)
                        """, (node_id, actor, reason or "Retracted entry", now_ts))
                    except Exception:
                        pass
                    conn.commit()
                    return True
                return False
            finally:
                conn.close()

    def supersede_memory(
        self,
        target_id: str,
        by_id: str,
        reason: str = "",
        actor: str = "human",
    ) -> bool:
        """Explicitly supersede a memory node with a newer memory node."""
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (target_id,))
                if cursor.rowcount > 0:
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO edges (child_id, parent_id, relation, reason, created_at, created_by)
                            VALUES (?, ?, 'supersedes', ?, ?, ?)
                        """, (by_id, target_id, reason, now_ts, actor))
                        conn.execute("""
                            INSERT INTO lifecycle_events (node_id, event, actor, reason, at)
                            VALUES (?, 'superseded', ?, ?, ?)
                        """, (target_id, actor, reason or f"Superseded by {by_id}", now_ts))
                    except Exception:
                        pass
                    conn.commit()
                    return True
                return False
            finally:
                conn.close()

    def clear_all_memories(self) -> int:
        """Delete all memories in this project database, clearing edges and markdown category directories."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM memories")
                count = cursor.rowcount
                if self._fts_available:
                    conn.execute("DELETE FROM memories_fts")
                try:
                    conn.execute("DELETE FROM edges")
                    conn.execute("DELETE FROM lifecycle_events")
                except Exception:
                    pass
                conn.commit()
                # Clean markdown files
                for t in ("decision", "architecture", "hack", "command", "error", "context"):
                    cat_dir = self.db_path.parent / t
                    if cat_dir.exists():
                        for f in cat_dir.glob("*.md"):
                            try:
                                f.unlink()
                            except Exception:
                                pass
                return count
            finally:
                conn.close()

    def search_hybrid(
        self,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
        scope_hint: Optional[List[str]] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_superseded: bool = False,
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """Execute hybrid search combining BM25 keyword matching and dense vector similarity via RRF."""
        with self._lock:
            conn = self._get_connection()
            try:
                from ..search.hybrid import HybridSearchEngine
                return HybridSearchEngine.search(
                    conn=conn,
                    query=query,
                    limit=limit,
                    mode=mode,
                    scope_hint=scope_hint,
                    type_filter=memory_type,
                    tags=tags,
                    include_superseded=include_superseded,
                    debug=debug,
                )
            finally:
                conn.close()

    def reindex_all(self, progress: bool = True) -> Tuple[int, int]:
        """Resumable backfill of vector embeddings for all memories lacking embeddings."""
        from ..search.embeddings import EmbeddingService
        from ..search.hybrid import build_embed_text
        from ..search.vectordb import normalize, serialize_f32

        embed_svc = EmbeddingService.get()
        if not embed_svc.available:
            return 0, 0

        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, title, tags, summary, content, timestamp FROM memories WHERE embedded_at IS NULL"
                ).fetchall()
                total = len(rows)
                if total == 0:
                    return 0, 0

                done = 0
                batch_size = 64
                for i in range(0, total, batch_size):
                    chunk = rows[i:i + batch_size]
                    texts = []
                    for r in chunk:
                        import json
                        tags_list = json.loads(r[2]) if r[2] else []
                        texts.append(build_embed_text(title=r[1], tags=tags_list, summary=r[3], content=r[4]))

                    vecs = embed_svc.embed_documents(texts)
                    for r, v in zip(chunk, vecs):
                        norm_v = normalize(v)
                        blob = serialize_f32(norm_v)
                        conn.execute("UPDATE memories SET embedding = ?, embedded_at = ? WHERE id = ?", (blob, r[5], r[0]))
                    done += len(chunk)
                    conn.commit()
                return done, total
            finally:
                conn.close()


