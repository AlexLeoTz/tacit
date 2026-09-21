"""Tests for PageRank authority over the memory DAG.

The important properties are the ones that made us deviate from textbook
PageRank: roots must dominate their descendants (not everything collapse to a
flat score), superseded links must not confer authority, and an unlinked project
must yield a neutral multiplier rather than a fake ordering.
"""

from dataclasses import dataclass, field
from typing import List

from src.core.authority import (
    build_link_graph,
    compute_authority,
    normalize,
    pagerank,
)


@dataclass
class FakeNode:
    id: str
    parents: List[str] = field(default_factory=list)


def _authority(outgoing, ids=None, **kwargs):
    ids = ids or list(outgoing)
    return normalize(pagerank(ids, outgoing, **kwargs))


# ---------------------------------------------------------------------------
# Core ranking behaviour
# ---------------------------------------------------------------------------

def test_root_outranks_its_descendants_in_a_chain():
    """C derives from B derives from A: A is the foundation."""
    scores = _authority({"A": [], "B": ["A"], "C": ["B"]})

    assert scores["A"] > scores["B"] > scores["C"]
    assert scores["A"] == 1.0


def test_hub_with_many_backlinks_tops_a_star():
    scores = _authority({"A": [], "B": ["A"], "C": ["A"], "D": ["A"]})

    assert scores["A"] == 1.0
    assert scores["B"] == scores["C"] == scores["D"]


def test_deeper_descendants_contribute_less_than_direct_children():
    """A child built directly on the root is a stronger signal than a grandchild."""
    scores = _authority({"root": [], "child": ["root"], "grandchild": ["child"]})

    assert scores["child"] > scores["grandchild"]


def test_authority_is_normalised_into_unit_range():
    scores = _authority({"A": [], "B": ["A"], "C": ["B"], "D": ["C"]})

    assert max(scores.values()) == 1.0
    assert all(0.0 <= value <= 1.0 for value in scores.values())


def test_unlinked_project_yields_a_neutral_multiplier():
    """With nothing to say about authority the ranking must fall back to relevance."""
    scores = _authority({"A": [], "B": [], "C": []})

    assert set(scores.values()) == {1.0}


def test_empty_graph_returns_empty_scores():
    assert pagerank([], {}) == {}
    assert compute_authority([]) == {}


def test_single_node_is_not_a_special_case_failure():
    assert _authority({"A": []}) == {"A": 1.0}


def test_cycles_converge_instead_of_diverging():
    """The graph is meant to be acyclic, but a bad edge must not hang or NaN."""
    scores = _authority({"A": ["B"], "B": ["A"]})

    assert all(value == value for value in scores.values())  # no NaN
    assert max(scores.values()) == 1.0


def test_lower_damping_flattens_the_ranking():
    outgoing = {"root": [], "a": ["root"], "b": ["a"], "c": ["b"]}

    sharp = _authority(outgoing, damping=0.95)
    flat = _authority(outgoing, damping=0.05)

    assert sharp["c"] < flat["c"]


def test_split_votes_are_divided_between_parents():
    """A memory citing two parents gives each half a vote, not a full one."""
    outgoing = {
        "whole": [],
        "shared": [],
        "other": [],
        "c1": ["whole"],
        "c2": ["shared", "other"],
    }
    scores = _authority(outgoing)

    assert scores["whole"] > scores["shared"]
    assert scores["shared"] == scores["other"], "both parents of c2 split the vote evenly"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def test_link_graph_uses_node_parents_when_no_edges_table():
    ids, outgoing = build_link_graph([FakeNode("a"), FakeNode("b", ["a"])])

    assert ids == ["a", "b"]
    assert outgoing == {"a": [], "b": ["a"]}


def test_link_graph_ignores_supersedes_edges():
    """Being corrected is not importance."""
    nodes = [FakeNode("old"), FakeNode("new")]
    edges = [{"child_id": "new", "parent_id": "old", "relation": "supersedes"}]

    _, outgoing = build_link_graph(nodes, edges)

    assert outgoing == {"old": [], "new": []}


def test_link_graph_drops_links_to_inactive_nodes():
    nodes = [FakeNode("live", ["deleted"])]
    edges = [{"child_id": "live", "parent_id": "deleted", "relation": "derives_from"}]

    _, outgoing = build_link_graph(nodes, edges)

    assert outgoing["live"] == []


def test_link_graph_deduplicates_repeated_parents():
    nodes = [FakeNode("root"), FakeNode("child", ["root", "root"])]

    _, outgoing = build_link_graph(nodes)

    assert outgoing["child"] == ["root"]


def test_empty_edges_table_falls_back_to_node_parents():
    """An empty ``edges`` table means "no edge data", not "an unlinked graph".

    Older databases wrote ``parents`` on the node without populating ``edges``,
    so falling back keeps them ranked instead of flattening them to neutral.
    """
    nodes = [FakeNode("root"), FakeNode("child", ["root"])]

    scores = compute_authority(nodes, [])

    assert scores["root"] == 1.0
    assert scores["root"] > scores["child"]


def test_compute_authority_end_to_end():
    nodes = [FakeNode("root"), FakeNode("child", ["root"]), FakeNode("leaf", ["child"])]
    edges = [
        {"child_id": "child", "parent_id": "root", "relation": "derives_from"},
        {"child_id": "leaf", "parent_id": "child", "relation": "derives_from"},
    ]

    scores = compute_authority(nodes, edges)

    assert scores["root"] == 1.0
    assert scores["root"] > scores["child"] > scores["leaf"]
