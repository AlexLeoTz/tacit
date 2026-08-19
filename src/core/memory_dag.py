"""Directed Acyclic Graph (DAG) for managing project memory relationships and lineage."""

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .memory_node import MemoryNode


class MemoryDAG:
    """Directed Acyclic Graph for memory relationships and dependency analysis."""

    def __init__(self):
        self.nodes: Dict[str, MemoryNode] = {}
        self.edges: Dict[str, Set[str]] = defaultdict(set)  # parent -> children
        self.reverse_edges: Dict[str, Set[str]] = defaultdict(set)  # child -> parents
        self.timeline: List[Tuple[float, str]] = []  # (timestamp, node_id)
        self.type_index: Dict[str, Set[str]] = defaultdict(set)
        self.tag_index: Dict[str, Set[str]] = defaultdict(set)

    def add_node(self, node: MemoryNode) -> bool:
        """Add a memory node to the DAG with validation for immutability, dependencies, and cycle freedom."""
        # Check immutability
        if node.id in self.nodes:
            return False

        # Validate that all declared parents exist in the DAG
        for parent_id in node.parents:
            if parent_id not in self.nodes:
                raise ValueError(f"Parent memory node '{parent_id}' not found in DAG.")

        # Validate that adding this node does not introduce a cycle
        if self._would_create_cycle(node):
            raise ValueError(f"Adding memory node '{node.id}' would introduce a cycle in DAG.")

        # Register node
        self.nodes[node.id] = node

        # Update causal relationships
        for parent_id in node.parents:
            self.edges[parent_id].add(node.id)
            self.reverse_edges[node.id].add(parent_id)

        # Update secondary timeline index
        self.timeline.append((node.timestamp, node.id))
        self.timeline.sort(key=lambda x: x[0])

        # Update category and tag indices
        self.type_index[node.type].add(node.id)
        for tag in node.tags:
            self.tag_index[tag].add(node.id)

        return True

    def _would_create_cycle(self, node: MemoryNode) -> bool:
        """Check if adding node would create a cycle in the DAG."""
        visited = set()

        def dfs(current_id: str) -> bool:
            if current_id == node.id:
                return True
            if current_id in visited:
                return False
            visited.add(current_id)

            for parent_id in self.reverse_edges.get(current_id, set()):
                if dfs(parent_id):
                    return True
            return False

        for parent_id in node.parents:
            if dfs(parent_id):
                return True

        return False

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        """Retrieve a node by its ID."""
        return self.nodes.get(node_id)

    def get_ancestors(self, node_id: str) -> Set[str]:
        """Get all causal ancestors (transitive parents) of a node."""
        ancestors: Set[str] = set()

        def dfs(current_id: str):
            for parent_id in self.reverse_edges.get(current_id, set()):
                if parent_id not in ancestors:
                    ancestors.add(parent_id)
                    dfs(parent_id)

        dfs(node_id)
        return ancestors

    def get_descendants(self, node_id: str) -> Set[str]:
        """Get all causal descendants (transitive children) of a node."""
        descendants: Set[str] = set()

        def dfs(current_id: str):
            for child_id in self.edges.get(current_id, set()):
                if child_id not in descendants:
                    descendants.add(child_id)
                    dfs(child_id)

        dfs(node_id)
        return descendants

    def get_by_type(self, memory_type: str) -> List[MemoryNode]:
        """Get all nodes matching a specified type."""
        return [self.nodes[nid] for nid in self.type_index.get(memory_type, set())]

    def get_by_tag(self, tag: str) -> List[MemoryNode]:
        """Get all nodes tagged with a specific tag."""
        return [self.nodes[nid] for nid in self.tag_index.get(tag, set())]

    def get_time_range(self, start: float, end: float) -> List[MemoryNode]:
        """Get nodes within a specific timestamp interval."""
        result = []
        for ts, nid in self.timeline:
            if start <= ts <= end:
                result.append(self.nodes[nid])
        return result

    def get_all_ordered(self, reverse: bool = False) -> List[MemoryNode]:
        """Get all nodes sorted by timestamp."""
        ordered = [self.nodes[nid] for _, nid in self.timeline]
        if reverse:
            ordered.reverse()
        return ordered

    def verify_integrity(self) -> bool:
        """Verify the cryptographic integrity of every node in the DAG."""
        for node in self.nodes.values():
            if not node.verify():
                return False
        return True

    def build_from_nodes(self, nodes: List[MemoryNode]) -> None:
        """Bulk populate DAG from a list of memory nodes ordered chronologically."""
        # Sort nodes chronologically
        sorted_nodes = sorted(nodes, key=lambda n: n.timestamp)
        for node in sorted_nodes:
            self.add_node(node)
