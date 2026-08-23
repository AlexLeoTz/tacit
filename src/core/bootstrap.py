"""Bootstrap Relevance Scoring and Briefing Engine for Tacit.

Replaces naive timeframe bootstrapping with a DAG-centrality, impact, recency-decay,
and token-budgeted multi-tier briefing algorithm.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .memory_node import MemoryNode
from ..utils.config import Config


# ==============================================================================
# Stage 0 — Configuration & Default Weights
# ==============================================================================

WEIGHTS = {
    "impact": 0.35,      # Agent-assigned severity (noisy -> moderate trust)
    "centrality": 0.40,  # How many later active decisions were built on this
    "recency": 0.25,     # Gentle freshness bias, never decisive alone
}

IMPACT_SCORES = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

CENTRALITY_SATURATION_K = 8    # Descendant count where centrality ~= 0.89
RECENCY_HALF_LIFE_DAYS = 180   # A memory loses half its recency score in 6 months
PENALTY_MAX = 0.30             # Max deduction when a neighbor was superseded
PENALTY_HALF_LIFE_DAYS = 60    # The deduction fades over ~2 months

TOKEN_BUDGET = Config.TOKEN_BUDGET
FULL_TIER_BUDGET_FRACTION = 0.60  # 60% of budget -> full content, rest -> one-liners
MIN_FULL_ENTRIES = 3              # Always brief deeply on at least 3 nodes if available
MAX_TAG_SHARE_IN_FULL = 0.5       # Diversity guard: max fraction of deep tier for 1 tag

TYPE_PRIOR = {"command": 0.0}     # Optional category prior adjustments


@dataclass
class Features:
    """Computed ranking feature values for a candidate memory node."""

    impact: float
    centrality: float
    recency: float
    penalty: float


@dataclass
class ScoredNode:
    """A memory node scored, ranked, and packaged with feature breakdown."""

    node: MemoryNode
    score: float
    features: Features
    rank: int = 0


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length (heuristic: ~4 chars per token)."""
    return max(1, len(text) // 4)


def dominant_tag(node: MemoryNode) -> str:
    """Extract primary tag or category type for diversity partitioning."""
    if node.tags and len(node.tags) > 0:
        return node.tags[0].strip().lower()
    return node.type.strip().lower()


def topological_sort(nodes: List[str], children: Dict[str, Set[str]]) -> List[str]:
    """Perform topological sort over nodes (returns topological order, or arbitrary on cycles)."""
    in_degree: Dict[str, int] = {n: 0 for n in nodes}
    for u in nodes:
        for v in children.get(u, set()):
            if v in in_degree:
                in_degree[v] += 1

    queue = [n for n in nodes if in_degree[n] == 0]
    result = []

    while queue:
        u = queue.pop(0)
        result.append(u)
        for v in children.get(u, set()):
            if v in in_degree:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

    # Append any remaining nodes (if cycle occurred)
    for n in nodes:
        if n not in result:
            result.append(n)

    return result


class BootstrapEngine:
    """Autonomous briefing engine executing relevance scoring and token assembly."""

    @classmethod
    def compute_descendant_counts(
        cls,
        active_nodes: List[MemoryNode],
        edges: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Compute distinct active descendant count for each node via 'derives_from' edges.

        Supersedes edges do NOT count toward centrality (being corrected is not importance).
        """
        active_ids = {n.id for n in active_nodes}
        children: Dict[str, Set[str]] = defaultdict(set)

        # Build adjacency graph from explicit edges table or fallback to node.parents
        if edges:
            for e in edges:
                parent_id = e.get("parent_id")
                child_id = e.get("child_id")
                relation = e.get("relation", "derives_from")
                if relation == "derives_from" and parent_id in active_ids and child_id in active_ids:
                    children[parent_id].add(child_id)
        else:
            for node in active_nodes:
                for parent_id in node.parents:
                    if parent_id in active_ids:
                        children[parent_id].add(node.id)

        all_node_ids = list(active_ids)
        topo_order = topological_sort(all_node_ids, children)

        desc_sets: Dict[str, Set[str]] = defaultdict(set)
        # Process in reverse topological order (leaves first)
        for nid in reversed(topo_order):
            s: Set[str] = set()
            for c in children.get(nid, set()):
                s.add(c)
                s.update(desc_sets.get(c, set()))
            desc_sets[nid] = s

        return {nid: len(desc_sets.get(nid, set())) for nid in all_node_ids}

    @classmethod
    def compute_node_features(
        cls,
        node: MemoryNode,
        now_ts: float,
        desc_counts: Dict[str, int],
        superseded_events: Dict[str, float],
        neighbor_map: Dict[str, Set[str]],
    ) -> Features:
        """Compute normalized [0, 1] feature terms and implication penalties."""
        f_impact = IMPACT_SCORES.get(node.impact.lower(), 0.6)

        # Saturating centrality curve: 0 -> 0.0, 8 -> 0.50, ...
        n = desc_counts.get(node.id, 0)
        f_centrality = float(n) / float(n + CENTRALITY_SATURATION_K)

        # Half-life decay for recency
        age_days = max(0.0, (now_ts - node.timestamp) / 86400.0)
        f_recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)

        # Implication penalty: if a direct neighbor (parent or child) was superseded recently
        penalty = 0.0
        direct_neighbors = neighbor_map.get(node.id, set())
        for nb_id in direct_neighbors:
            if nb_id in superseded_events:
                event_ts = superseded_events[nb_id]
                days_since = max(0.0, (now_ts - event_ts) / 86400.0)
                deduction = PENALTY_MAX * (0.5 ** (days_since / PENALTY_HALF_LIFE_DAYS))
                penalty = max(penalty, deduction)

        return Features(
            impact=f_impact,
            centrality=f_centrality,
            recency=f_recency,
            penalty=penalty,
        )

    @classmethod
    def score(cls, f: Features, node_type: str) -> float:
        """Compute composite score from features."""
        base = (
            WEIGHTS["impact"] * f.impact
            + WEIGHTS["centrality"] * f.centrality
            + WEIGHTS["recency"] * f.recency
        )
        total = base + TYPE_PRIOR.get(node_type.lower(), 0.0) - f.penalty
        return total

    @classmethod
    def rank_and_diversify(
        cls,
        scored_nodes: List[Tuple[float, MemoryNode, Features]],
    ) -> List[ScoredNode]:
        """Rank candidates with diversity guard to avoid deep-tier tag starvation."""
        # Sort descending by score, tie-break by timestamp descending
        scored_nodes.sort(key=lambda item: (-item[0], -item[1].timestamp))

        full_pool_size = 15
        pool = scored_nodes[:full_pool_size]
        rest = scored_nodes[full_pool_size:]

        picked: List[Tuple[float, MemoryNode, Features]] = []
        tag_counts: Counter = Counter()
        max_per_tag = max(1, int(MIN_FULL_ENTRIES * MAX_TAG_SHARE_IN_FULL))
        deferred: List[Tuple[float, MemoryNode, Features]] = []

        for item in pool:
            score_val, node, feat = item
            tag = dominant_tag(node)
            if tag_counts[tag] >= max_per_tag and len(picked) < MIN_FULL_ENTRIES:
                deferred.append(item)
            else:
                picked.append(item)
                tag_counts[tag] += 1

        ordered_all = picked + deferred + rest
        return [
            ScoredNode(node=node, score=score_val, features=feat, rank=idx + 1)
            for idx, (score_val, node, feat) in enumerate(ordered_all)
        ]

    @classmethod
    def render_full_node(cls, scored: ScoredNode, now_ts: float) -> str:
        """Render complete content block for Tier 1 entry."""
        node = scored.node
        age_days = int(max(0.0, (now_ts - node.timestamp) / 86400.0))
        age_str = f"{age_days}d old" if age_days > 0 else "today"

        lines = [
            f"◆ {node.type.upper()} · {node.impact.capitalize()} impact · {age_str} · score {scored.score:.2f} (`{node.id[:8]}`)",
            f'  "{node.title or node.summary}"',
            f"  {node.content.strip()}",
        ]
        if node.parents:
            parent_refs = ", ".join(f"`{p[:8]}`" for p in node.parents)
            lines.append(f"  ↳ built on: {parent_refs}")
        return "\n".join(lines)

    @classmethod
    def render_summary_node(cls, scored: ScoredNode) -> str:
        """Render concise one-line summary for Tier 2 entry."""
        node = scored.node
        title_or_summary = node.title or node.summary
        return f"  {dominant_tag(node):<12} • {title_or_summary} (`{node.id[:8]}`)"

    @classmethod
    def assemble(
        cls,
        ranked: List[ScoredNode],
        budget: int = TOKEN_BUDGET,
        now_ts: Optional[float] = None,
    ) -> Tuple[List[ScoredNode], Dict[str, List[ScoredNode]]]:
        """Assemble Tier 1 (Full) and Tier 2 (One-liners) under token budget."""
        now_ts = now_ts or datetime.now(timezone.utc).timestamp()
        full_budget = int(budget * FULL_TIER_BUDGET_FRACTION)
        brief_budget = budget - full_budget

        full: List[ScoredNode] = []
        used_full_tokens = 0

        for item in ranked:
            text = cls.render_full_node(item, now_ts)
            cost = estimate_tokens(text)
            if len(full) >= MIN_FULL_ENTRIES and (used_full_tokens + cost > full_budget):
                break
            full.append(item)
            used_full_tokens += cost

        # Tier 2: One-liners
        remaining = ranked[len(full):]
        brief_by_tag: Dict[str, List[ScoredNode]] = defaultdict(list)
        used_brief_tokens = 0

        for item in remaining:
            text = cls.render_summary_node(item)
            cost = estimate_tokens(text)
            if used_brief_tokens + cost > brief_budget:
                break
            tag = dominant_tag(item.node)
            brief_by_tag[tag].append(item)
            used_brief_tokens += cost

        return full, brief_by_tag

    @classmethod
    def generate_briefing(
        cls,
        storage: Any,
        budget: int = TOKEN_BUDGET,
        now_dt: Optional[datetime] = None,
        scope_hint: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute full bootstrap briefing generation against storage."""
        now_dt = now_dt or datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()
        date_str = now_dt.strftime("%Y-%m-%d %H:%M")

        # Stage 1: Select active candidates
        active_nodes = storage.get_active_memories()
        if not active_nodes:
            return {
                "count": 0,
                "full_count": 0,
                "brief_count": 0,
                "formatted": f"════ PROJECT BRIEFING · generated {date_str} ════\n\n(No active institutional memories found. Project starts with empty context.)\n═══════════════════════════════════════════════════════",
                "full": [],
                "brief": {},
            }

        # Stage 2: Graph analysis & feature computation
        edges = storage.get_edges() if hasattr(storage, "get_edges") else []
        lifecycle_events = storage.get_lifecycle_events() if hasattr(storage, "get_lifecycle_events") else []

        # Map superseded event timestamps by node_id
        superseded_events: Dict[str, float] = {}
        for ev in lifecycle_events:
            if ev.get("event") == "superseded":
                nid = ev.get("node_id")
                at_val = ev.get("at", now_ts)
                if isinstance(at_val, (int, float)):
                    superseded_events[nid] = float(at_val)

        # Build neighbor map (parents and children) for direct implication checks
        neighbor_map: Dict[str, Set[str]] = defaultdict(set)
        for n in active_nodes:
            for p in n.parents:
                neighbor_map[n.id].add(p)
                neighbor_map[p].add(n.id)
            for c in n.children:
                neighbor_map[n.id].add(c)
                neighbor_map[c].add(n.id)

        desc_counts = cls.compute_descendant_counts(active_nodes, edges)

        # Stage 3: Score all candidates
        scored_candidates: List[Tuple[float, MemoryNode, Features]] = []
        for node in active_nodes:
            features = cls.compute_node_features(
                node=node,
                now_ts=now_ts,
                desc_counts=desc_counts,
                superseded_events=superseded_events,
                neighbor_map=neighbor_map,
            )
            score_val = cls.score(features, node.type)
            # Drop negatively scored nodes (actively misleading)
            if score_val >= 0.0:
                scored_candidates.append((score_val, node, features))

        if not scored_candidates:
            return {
                "count": 0,
                "full_count": 0,
                "brief_count": 0,
                "formatted": f"════ PROJECT BRIEFING · generated {date_str} ════\n\n(No high-relevance active memories found.)\n═══════════════════════════════════════════════════════",
                "full": [],
                "brief": {},
            }

        # Stage 4: Rank + Diversity Guard
        ranked_nodes = cls.rank_and_diversify(scored_candidates)

        # Stage 5: Token-budgeted Assembly
        full_tier, brief_tier = cls.assemble(ranked_nodes, budget=budget, now_ts=now_ts)

        # Stage 6: Render output briefing
        lines = [
            f"════ PROJECT BRIEFING · generated {date_str} ════\n",
            "── Core context (read fully) ──────────────────────────",
        ]

        for item in full_tier:
            lines.append(cls.render_full_node(item, now_ts))
            lines.append("")

        if brief_tier:
            lines.append("── Also relevant ──────────────────────────────────────")
            for tag, items in sorted(brief_tier.items()):
                for item in items:
                    lines.append(cls.render_summary_node(item))
            lines.append("")

        lines.append("═══════════════════════════════════════════════════════")
        briefing_text = "\n".join(lines)

        total_brief = sum(len(v) for v in brief_tier.values())

        return {
            "count": len(full_tier) + total_brief,
            "full_count": len(full_tier),
            "brief_count": total_brief,
            "formatted": briefing_text,
            "full": [item.node.to_dict() for item in full_tier],
            "brief": {tag: [item.node.to_dict() for item in items] for tag, items in brief_tier.items()},
        }
