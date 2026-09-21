"""PageRank authority over the Tacit memory graph.

Every active memory is treated as a page, and its causal links are its votes.
An edge ``child --derives_from--> parent`` means "this memory was built on that
one", so the parent collects rank from everything that traces back to it — the
same backlink intuition that ranks web pages. A memory cited by three
foundational decisions outranks one cited by three throwaway notes, which a
plain descendant count cannot express.

Two deliberate departures from textbook PageRank, both forced by the shape of
this graph:

1. **Proportional dangling redistribution.** Tacit's graph is a DAG whose edges
   point child -> parent, so roots are sinks, and a young project is mostly
   isolated roots with no links at all. Textbook PageRank redistributes the mass
   trapped at dangling nodes *uniformly*, which adds a large flat floor and
   collapses every node toward the same score — the opposite of useful ranking.
   Redistributing in proportion to current rank keeps the discrimination that
   PageRank exists to provide.
2. **Normalisation to [0, 1].** The result is used as a multiplier next to query
   relevance, so it is divided by its maximum and always spans a known range.

When the graph has no links at all, every node converges to the same value and
normalisation yields 1.0 for everyone — a neutral multiplier that leaves
relevance to decide, rather than a fake ordering.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Standard PageRank damping factor.
DAMPING = 0.85

#: Power-iteration cap; convergence is normally reached well before this.
ITERATIONS = 30

#: L1 convergence threshold.
TOLERANCE = 1e-9


def build_link_graph_from_pairs(
    pairs: Iterable[Tuple[str, Sequence[str]]],
    edges: Optional[Iterable[Dict[str, Any]]] = None,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Same as :func:`build_link_graph` but from ``(node_id, parents)`` pairs.

    Lets callers build the graph straight from SQL without materialising a
    ``MemoryNode`` (and its JSON decoding) for every row in the project.
    """
    node_ids: List[str] = []
    stored_parents: Dict[str, List[str]] = {}
    for node_id, parents in pairs:
        node_id = str(node_id)
        if node_id in stored_parents:
            continue
        node_ids.append(node_id)
        stored_parents[node_id] = [str(p) for p in (parents or [])]

    known = set(node_ids)
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}

    if edges:
        for edge in edges:
            if edge.get("relation", "derives_from") != "derives_from":
                continue
            child_id = edge.get("child_id")
            parent_id = edge.get("parent_id")
            if child_id in known and parent_id in known:
                if parent_id not in outgoing[child_id]:
                    outgoing[child_id].append(parent_id)
    else:
        for node_id in node_ids:
            for parent_id in stored_parents[node_id]:
                if parent_id in known and parent_id not in outgoing[node_id]:
                    outgoing[node_id].append(parent_id)

    return node_ids, outgoing


def build_link_graph(
    nodes: Sequence[Any],
    edges: Optional[Iterable[Dict[str, Any]]] = None,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Build ``child -> [parents]`` from the ``edges`` table, or from ``node.parents``.

    Only ``derives_from`` relations count. A ``supersedes`` edge is excluded on
    purpose: being corrected is not importance. Links to superseded or retracted
    nodes are dropped, so authority always reflects the surviving graph.

    A falsy ``edges`` argument means "no edge data available" and falls back to
    each node's ``parents`` list, which is what databases written before the
    ``edges`` table rely on. Passing an empty list is therefore *not* a way to
    declare an unlinked graph.
    """
    return build_link_graph_from_pairs(
        ((node.id, getattr(node, "parents", None) or []) for node in nodes), edges
    )


def pagerank(
    node_ids: Sequence[str],
    outgoing: Dict[str, List[str]],
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
    tolerance: float = TOLERANCE,
) -> Dict[str, float]:
    """Run damped PageRank; mass at link-less nodes is spread proportionally."""
    count = len(node_ids)
    if count == 0:
        return {}

    rank = {node_id: 1.0 / count for node_id in node_ids}
    teleport = (1.0 - damping) / count

    for _ in range(max(1, iterations)):
        updated = {node_id: teleport for node_id in node_ids}
        dangling_mass = 0.0

        for node_id in node_ids:
            parents = outgoing.get(node_id)
            if not parents:
                dangling_mass += rank[node_id]
                continue
            share = damping * rank[node_id] / len(parents)
            for parent_id in parents:
                updated[parent_id] += share

        total = sum(rank.values())
        if dangling_mass and total > 0.0:
            # Proportional, not uniform: uniform redistribution is what makes
            # sparse DAGs collapse to a flat ranking.
            scale = damping * dangling_mass / total
            for node_id in node_ids:
                updated[node_id] += scale * rank[node_id]

        delta = sum(abs(updated[node_id] - rank[node_id]) for node_id in node_ids)
        rank = updated
        if delta < tolerance:
            break

    return rank


def normalize(scores: Dict[str, float]) -> Dict[str, float]:
    """Scale scores into [0, 1] by their maximum; all-zero input maps to 0.0."""
    if not scores:
        return {}
    peak = max(scores.values())
    if peak <= 0.0:
        return {node_id: 0.0 for node_id in scores}
    return {node_id: value / peak for node_id, value in scores.items()}


def compute_authority_from_pairs(
    pairs: Iterable[Tuple[str, Sequence[str]]],
    edges: Optional[Iterable[Dict[str, Any]]] = None,
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
) -> Dict[str, float]:
    """Row-based variant of :func:`compute_authority` for SQL callers."""
    node_ids, outgoing = build_link_graph_from_pairs(pairs, edges)
    if not node_ids:
        return {}
    if not any(outgoing.values()):
        return {node_id: 1.0 for node_id in node_ids}
    return normalize(pagerank(node_ids, outgoing, damping=damping, iterations=iterations))


def compute_authority(
    nodes: Sequence[Any],
    edges: Optional[Iterable[Dict[str, Any]]] = None,
    damping: float = DAMPING,
    iterations: int = ITERATIONS,
) -> Dict[str, float]:
    """Return a normalised [0, 1] authority score per active memory id.

    Unlinked graphs yield 1.0 everywhere, which is deliberately neutral: callers
    multiply by this value, so with nothing to say about authority the ranking
    falls back to pure relevance.
    """
    return compute_authority_from_pairs(
        ((node.id, getattr(node, "parents", None) or []) for node in nodes),
        edges,
        damping=damping,
        iterations=iterations,
    )
