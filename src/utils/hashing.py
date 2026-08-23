"""Cryptographic hash utilities for Tacit."""

import hashlib
import json
from typing import Any, Iterable


def calculate_sha256(data: str | bytes) -> str:
    """Calculate SHA-256 hash of a string or byte payload."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def calculate_content_hash(content: str, summary: str, title: str, timestamp: float) -> str:
    """Calculate deterministic SHA-256 hash of core memory content."""
    payload = json.dumps(
        {
            "content": content,
            "summary": summary,
            "title": title,
            "timestamp": timestamp,
        },
        sort_keys=True,
    )
    return calculate_sha256(payload)


def calculate_merkle_root(content_hash: str, timestamp: float, parents: Iterable[str]) -> str:
    """Calculate Merkle root combining content hash, timestamp, and sorted parent hashes."""
    parent_hashes = sorted(parents)
    merkle_input = f"{content_hash}:{timestamp}:{','.join(parent_hashes)}"
    return calculate_sha256(merkle_input)
