"""Merkle tree calculation for verifying immutable memory integrity."""

from typing import List, Optional
from ..utils.hashing import calculate_sha256


class MerkleTree:
    """Computes and validates Merkle tree hashes across memory nodes."""

    def __init__(self, leaf_hashes: Optional[List[str]] = None):
        self.leaves: List[str] = leaf_hashes or []
        self.root: str = self._build_tree(self.leaves)

    def _build_tree(self, leaves: List[str]) -> str:
        """Recursively build Merkle root hash from leaves."""
        if not leaves:
            return calculate_sha256("")
        if len(leaves) == 1:
            return leaves[0]

        current_layer = list(leaves)
        while len(current_layer) > 1:
            next_layer = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                if i + 1 < len(current_layer):
                    right = current_layer[i + 1]
                else:
                    right = left  # Duplicate last element if odd number
                combined = f"{left}:{right}"
                next_layer.append(calculate_sha256(combined))
            current_layer = next_layer

        return current_layer[0]

    def add_leaf(self, leaf_hash: str) -> str:
        """Add a leaf hash and recompute the Merkle root."""
        self.leaves.append(leaf_hash)
        self.root = self._build_tree(self.leaves)
        return self.root

    def get_root(self) -> str:
        """Return the current Merkle root."""
        return self.root

    def verify_consistency(self, expected_root: str) -> bool:
        """Verify the current tree root matches expected root."""
        return self.root == expected_root
