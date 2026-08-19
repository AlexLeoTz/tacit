"""Temporal and time-sliced query utilities for Project Memory Cortex."""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage


class TemporalSearch:
    """Time-based query and grouping engine."""

    TIMEFRAME_DAYS = {
        "session": 1,
        "day": 1,
        "yesterday": 2,
        "week": 7,
        "month": 30,
        "quarter": 90,
        "year": 365,
        "all": 3650,
    }

    def __init__(self, storage: MemoryStorage):
        self.storage = storage

    def get_recent(
        self, days: int = 7, limit: int = 50, memory_type: Optional[str] = None
    ) -> List[MemoryNode]:
        """Get memories created within the last N days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        memories = self.storage.get_since(cutoff)
        if memory_type:
            memories = [m for m in memories if m.type == memory_type]
        # Return in descending order
        return sorted(memories, key=lambda m: m.timestamp, reverse=True)[:limit]

    def get_by_timeframe(
        self, timeframe: str = "week", limit: int = 100
    ) -> List[MemoryNode]:
        """Get memories matching predefined timeframe alias."""
        days = self.TIMEFRAME_DAYS.get(timeframe.lower(), 7)
        return self.get_recent(days=days, limit=limit)

    def group_by_type(self, memories: List[MemoryNode]) -> Dict[str, List[MemoryNode]]:
        """Group a list of memories by their category type."""
        grouped: Dict[str, List[MemoryNode]] = {
            "decision": [],
            "command": [],
            "hack": [],
            "architecture": [],
            "error": [],
            "context": [],
        }
        for node in memories:
            if node.type in grouped:
                grouped[node.type].append(node)
            else:
                grouped.setdefault(node.type, []).append(node)
        return grouped
