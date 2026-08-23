"""Vector math, serialization, and similarity search for Tacit."""

from __future__ import annotations

import math
import struct
from typing import Any, List, Optional, Tuple


def normalize(v: List[float]) -> List[float]:
    """Compute L2 normalized vector."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def serialize_f32(v: List[float]) -> bytes:
    """Serialize float vector to compact binary buffer."""
    return struct.pack(f"{len(v)}f", *v)


def deserialize_f32(blob: bytes) -> List[float]:
    """Deserialize float vector from binary buffer."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def enable_vec(db) -> bool:
    """Best-effort loading of sqlite-vec extension."""
    try:
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
            USING vec0(memory_id text primary key, embedding float[384])
        """)
        return True
    except Exception:
        return False
