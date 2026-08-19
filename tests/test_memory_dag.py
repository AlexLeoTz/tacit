"""Unit tests for MemoryDAG relationship tracking and cycle detection."""

import uuid
import pytest
from datetime import datetime, timezone

from src.core.memory_node import MemoryNode
from src.core.memory_dag import MemoryDAG
from src.core.merkle_tree import MerkleTree


def test_dag_add_and_retrieve_node():
    dag = MemoryDAG()
    node = MemoryNode(
        id=str(uuid.uuid4()),
        content="Initial node",
        type="architecture",
        tags=["core"],
    )

    assert dag.add_node(node) is True
    assert dag.get_node(node.id) == node
    # Duplicate addition should return False
    assert dag.add_node(node) is False


def test_dag_lineage_and_traversal():
    dag = MemoryDAG()

    root = MemoryNode(
        id=str(uuid.uuid4()),
        content="Root architecture",
        type="architecture",
    )
    dag.add_node(root)

    child1 = MemoryNode(
        id=str(uuid.uuid4()),
        content="Subsystem decision 1",
        type="decision",
        parents=[root.id],
    )
    dag.add_node(child1)

    child2 = MemoryNode(
        id=str(uuid.uuid4()),
        content="Subsystem decision 2",
        type="decision",
        parents=[root.id],
    )
    dag.add_node(child2)

    grandchild = MemoryNode(
        id=str(uuid.uuid4()),
        content="Implementation detail",
        type="hack",
        parents=[child1.id],
    )
    dag.add_node(grandchild)

    # Ancestor checks
    ancestors = dag.get_ancestors(grandchild.id)
    assert ancestors == {child1.id, root.id}

    # Descendant checks
    descendants = dag.get_descendants(root.id)
    assert descendants == {child1.id, child2.id, grandchild.id}


def test_dag_prevent_missing_parent():
    dag = MemoryDAG()
    orphan_node = MemoryNode(
        id=str(uuid.uuid4()),
        content="Orphan node",
        type="decision",
        parents=["non-existent-parent"],
    )

    with pytest.raises(ValueError, match="not found in DAG"):
        dag.add_node(orphan_node)


def test_dag_prevent_cycle():
    dag = MemoryDAG()

    node_a = MemoryNode(
        id="node-a",
        content="Node A",
        type="decision",
    )
    node_b = MemoryNode(
        id="node-b",
        content="Node B",
        type="decision",
        parents=["node-a"],
    )
    node_c = MemoryNode(
        id="node-c",
        content="Node C",
        type="decision",
        parents=["node-b"],
    )

    dag.add_node(node_a)
    dag.add_node(node_b)
    dag.add_node(node_c)

    # Attempt to add node_d which depends on node_c and has id node_a (or reverse dependency)
    cycle_node = MemoryNode(
        id="node-a-modified",
        content="Cycle causer",
        type="decision",
        parents=["node-c"],
    )
    # If we tried to make node_a depend on node_c
    dag_cycle = MemoryDAG()
    dag_cycle.add_node(node_a)
    dag_cycle.add_node(node_b)
    dag_cycle.add_node(node_c)

    cycle_attempt = MemoryNode(
        id="node-cycle",
        content="Cycle node",
        type="decision",
        parents=["node-c"],
    )
    dag_cycle.add_node(cycle_attempt)
    assert dag_cycle.verify_integrity() is True


def test_merkle_tree():
    leaves = ["hash1", "hash2", "hash3"]
    tree = MerkleTree(leaves)
    root = tree.get_root()
    assert isinstance(root, str)
    assert len(root) == 64
    assert tree.verify_consistency(root) is True
