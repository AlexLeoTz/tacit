"""SQLite-based storage layer with full-text search index for Project Memory Cortex."""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
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
                        metadata TEXT
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

    def add_memory(self, node: MemoryNode) -> bool:
        """Add memory node to SQLite database and update FTS index."""
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

                if self._fts_available:
                    tags_str = " ".join(node.tags)
                    conn.execute("""
                        INSERT INTO memories_fts(memory_id, content, summary, title, tags)
                        VALUES (?, ?, ?, ?, ?)
                    """, (node.id, node.content, node.summary, node.title, tags_str))

                conn.commit()
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
        """Perform full-text search matching query keywords."""
        with self._lock:
            conn = self._get_connection()
            try:
                if self._fts_available and query.strip():
                    # Clean/sanitize query for FTS5 syntax
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
                    like_query = f"%{query}%"
                    if memory_type:
                        sql = """
                            SELECT * FROM memories
                            WHERE (content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?)
                              AND type = ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (like_query, like_query, like_query, like_query, memory_type, limit)).fetchall()
                    else:
                        sql = """
                            SELECT * FROM memories
                            WHERE content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """
                        rows = conn.execute(sql, (like_query, like_query, like_query, like_query, limit)).fetchall()

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
        """Delete a single memory by ID from memories and FTS index."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM memories WHERE id = ?", (node_id,))
                deleted = cursor.rowcount > 0
                if self._fts_available and deleted:
                    conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (node_id,))
                conn.commit()
                return deleted
            finally:
                conn.close()

    def clear_all_memories(self) -> int:
        """Delete all memories in this project database."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM memories")
                count = cursor.rowcount
                if self._fts_available:
                    conn.execute("DELETE FROM memories_fts")
                conn.commit()
                return count
            finally:
                conn.close()
