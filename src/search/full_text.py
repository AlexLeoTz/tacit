"""Full-text search query handling and ranking for Project Memory Cortex."""

from typing import List, Optional
from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage


class FullTextSearch:
    """Full-text search engine executing against SQLite FTS5 index."""

    def __init__(self, storage: MemoryStorage):
        self.storage = storage

    def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[MemoryNode]:
        """Execute full-text search with optional type and tag filtering."""
        results = self.storage.search_full_text(
            query=query, limit=limit, memory_type=memory_type
        )
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [
                node
                for node in results
                if any(tag.lower() in tag_set for tag in node.tags)
            ]
        return results
