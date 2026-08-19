"""Probabilistic Bloom Filter implementation for fast in-memory key/tag existence checks."""

import hashlib
import math
from typing import List


class BloomFilter:
    """Space-efficient probabilistic data structure for set membership testing."""

    def __init__(self, expected_elements: int = 10000, false_positive_rate: float = 0.01):
        self.expected_elements = max(10, expected_elements)
        self.false_positive_rate = false_positive_rate

        # Optimal size of bit array: m = - (n * ln(p)) / (ln(2)^2)
        self.size = int(
            -(self.expected_elements * math.log(self.false_positive_rate))
            / (math.log(2) ** 2)
        )
        # Optimal number of hash functions: k = (m / n) * ln(2)
        self.hash_count = int((self.size / self.expected_elements) * math.log(2))
        self.bit_array = [False] * self.size

    def _hashes(self, item: str) -> List[int]:
        """Generate k hash indexes for an item using double hashing."""
        item_bytes = item.encode("utf-8")
        h1 = int(hashlib.sha256(item_bytes).hexdigest(), 16)
        h2 = int(hashlib.md5(item_bytes).hexdigest(), 16)

        indexes = []
        for i in range(self.hash_count):
            index = (h1 + i * h2) % self.size
            indexes.append(index)
        return indexes

    def add(self, item: str) -> None:
        """Add an item to the Bloom filter."""
        for index in self._hashes(item):
            self.bit_array[index] = True

    def contains(self, item: str) -> bool:
        """Check if item is possibly in the set."""
        return all(self.bit_array[index] for index in self._hashes(item))

    def __contains__(self, item: str) -> bool:
        return self.contains(item)
