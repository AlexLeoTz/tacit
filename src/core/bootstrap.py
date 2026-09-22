"""Bootstrap Relevance Scoring and Briefing Engine for Tacit.

Ranking is driven by **PageRank authority** (see ``src/core/authority.py``): a
memory that many later memories trace back to is worth bootstrapping an agent
with, whether or not it is recent. Impact and recency are retained as *bounded
multipliers* so they can reorder memories of comparable authority but can never
overturn a large authority gap, and the supersede penalty stays subtractive so a
memory sitting next to a correction can still be pushed down or out.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .authority import compute_authority
from .memory_node import MemoryNode
from ..utils.config import Config
from ..utils.scope import node_matches_scope


# ==============================================================================
# Stage 0 — Configuration & Default Weights
# ==============================================================================

#: Impact multiplier spans [0.6, 1.0]: a low-impact note is discounted, never
#: silenced, because impact is agent-assigned and therefore noisy.
IMPACT_FLOOR = 0.6

#: Recency multiplier spans [0.7, 1.0]. Authority already handles "is this
#: load-bearing"; recency only breaks ties between equally authoritative entries.
RECENCY_FLOOR = 0.7

IMPACT_SCORES = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

RECENCY_HALF_LIFE_DAYS = 180   # A memory loses half its recency score in 6 months
PENALTY_MAX = 0.30             # Max deduction when a neighbor was superseded
PENALTY_HALF_LIFE_DAYS = 60    # The deduction fades over ~2 months

TOKEN_BUDGET = Config.TOKEN_BUDGET
FULL_TIER_BUDGET_FRACTION = 0.60  # 60% of budget -> full content, rest -> one-liners
MIN_FULL_ENTRIES = 3              # Always brief deeply on at least 3 nodes if available
MAX_TAG_SHARE_IN_FULL = 0.5       # Diversity guard: max fraction of deep tier for 1 tag

#: Optional per-category multiplier, e.g. ``{"constraint": 0.2}`` to promote every
#: binding constraint. Applied as ``(1 + TYPE_PRIOR[type])``; values must be > -1.
TYPE_PRIOR: Dict[str, float] = {}

#: Relative timeframes accepted by ``tacit briefing --timeframe`` / ``memory_context``.
TIMEFRAME_UNITS = {
    "hour": 1 / 24,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "quarter": 91.0,
    "year": 365.0,
}


def parse_timeframe(timeframe: Optional[str], now_ts: Optional[float] = None) -> Optional[float]:
    """Return the oldest timestamp still in scope, or ``None`` for "everything".

    Accepts ``all``/``None``/empty, a relative name (``week``, ``30d``, ``6h``,
    ``2w``, ``year``) or an ISO date (``2026-01-31``). Unparseable input is
    treated as "all" rather than raising: a bad timeframe must not break an
    agent's session bootstrap.
    """
    if timeframe is None:
        return None
    text = str(timeframe).strip().lower()
    if not text or text in ("all", "any", "everything", "forever"):
        return None

    now_ts = now_ts or datetime.now(timezone.utc).timestamp()

    if text in TIMEFRAME_UNITS:
        return now_ts - TIMEFRAME_UNITS[text] * 86400.0

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hdwmy])", text)
    if match:
        amount = float(match.group(1))
        unit_days = {"h": 1 / 24, "d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}[match.group(2)]
        return now_ts - amount * unit_days * 86400.0

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass
class Features:
    """Computed ranking feature values for a candidate memory node."""

    authority: float   # PageRank authority, normalised to [0, 1]
    impact: float
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
    """Perform topological sort over nodes (returns topological order, or arbitrary on cycles).

    Retained as a graph utility; briefing ranking no longer uses it because
    PageRank replaced the descendant-count centrality it served.
    """
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
    def compute_node_features(
        cls,
        node: MemoryNode,
        now_ts: float,
        authority: float,
        superseded_events: Dict[str, float],
        neighbor_map: Dict[str, Set[str]],
    ) -> Features:
        """Collect the ranking features for a node; ``authority`` comes from PageRank."""
        f_impact = IMPACT_SCORES.get(node.impact.lower(), 0.6)

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
            authority=max(0.0, min(1.0, float(authority))),
            impact=f_impact,
            recency=f_recency,
            penalty=penalty,
        )

    @classmethod
    def score(cls, f: Features, node_type: str) -> float:
        """Combine features into a score where authority leads.

        ``authority * impact_multiplier * recency_multiplier - penalty``: the two
        multipliers are bounded into [0.6, 1.0] and [0.7, 1.0], so together they
        can move a memory by at most ~2.4x and cannot outvote a decisive
        authority gap. The supersede penalty stays subtractive so a memory
        sitting next to a correction can still be pushed out entirely.
        """
        impact_multiplier = IMPACT_FLOOR + (1.0 - IMPACT_FLOOR) * f.impact
        recency_multiplier = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * f.recency
        prior = 1.0 + TYPE_PRIOR.get(node_type.lower(), 0.0)
        return f.authority * impact_multiplier * recency_multiplier * prior - f.penalty

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
            f"◆ {node.type.upper()} · {node.impact.capitalize()} impact · {age_str} · score {scored.score:.2f} (`{node.id}`)",
            f'  "{node.title or node.summary}"',
            f"  {node.content.strip()}",
        ]
        if node.parents:
            # Full ids: `memory_get` requires the complete UUID, so a truncated
            # one here is a reference the reader cannot follow.
            parent_refs = ", ".join(f"`{p}`" for p in node.parents)
            lines.append(f"  ↳ built on: {parent_refs}")
        return "\n".join(lines)

    @classmethod
    def render_summary_node(cls, scored: ScoredNode) -> str:
        """Render concise one-line summary for Tier 2 entry."""
        node = scored.node
        title_or_summary = node.title or node.summary
        return f"  {dominant_tag(node):<12} • {title_or_summary} (`{node.id}`)"

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
    def project_map_line(cls, storage: Any) -> str:
        """One header line pointing at the captured project structure, if any.

        The map itself is a separate tool call on purpose: a briefing must stay
        inside its token budget, and an agent that only needs the layout should
        not pay for memories (or vice versa).
        """
        try:
            from . import project_tree

            root = Config.project_root_for_db(storage.db_path)
            store_dir = Config.get_memory_dir(root)
            settings = project_tree.tree_settings(store_dir)
            if not settings.get("enabled"):
                return ""
            summary = project_tree.snapshot_summary(store_dir)
            if not summary:
                return ""
        except Exception:
            return ""
        return f"── Project map: {summary} · call project_structure ──"

    @classmethod
    def generate_briefing(
        cls,
        storage: Any,
        budget: int = TOKEN_BUDGET,
        now_dt: Optional[datetime] = None,
        scope_hint: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute full bootstrap briefing generation against storage.

        ``timeframe`` filters which memories may appear, while authority is always
        computed over the *whole* active graph. Restricting PageRank to a recent
        window would leave a handful of nodes with almost no links between them,
        where every score is identical and the ranking means nothing.
        """
        now_dt = now_dt or datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()
        date_str = now_dt.strftime("%Y-%m-%d %H:%M")
        cutoff_ts = parse_timeframe(timeframe, now_ts)
        map_line = cls.project_map_line(storage)

        # Stage 1: Select active candidates
        active_nodes = storage.get_active_memories()
        if not active_nodes:
            return {
                "count": 0,
                "full_count": 0,
                "brief_count": 0,
                "formatted": f"════ PROJECT BRIEFING · generated {date_str} ════\n{map_line}\n(No active institutional memories found. Project starts with empty context.)\n═══════════════════════════════════════════════════════",
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

        authority_scores = compute_authority(active_nodes, edges)

        # Timeframe narrows what is shown, never the graph used to rank it.
        candidates = (
            [n for n in active_nodes if n.timestamp >= cutoff_ts]
            if cutoff_ts is not None
            else list(active_nodes)
        )
        if not candidates:
            return {
                "count": 0,
                "full_count": 0,
                "brief_count": 0,
                "formatted": f"════ PROJECT BRIEFING · generated {date_str} ════\n\n(No active memories in timeframe '{timeframe}'.)\n═══════════════════════════════════════════════════════",
                "full": [],
                "brief": {},
            }

        hints = [h.strip() for h in (scope_hint or []) if h and h.strip()]
        project_root = None
        try:
            project_root = Config.project_root_for_db(storage.db_path)
        except Exception:
            project_root = None
        # Stage 3: Score all candidates.
        #
        # Scope is a FILTER: a caller working in `backend/app` is not shown
        # memories recorded against `frontend/`, so a briefing can never mix
        # subsystems (or, when a store was wrongly shared, repositories).
        # Project-wide memories are the exception - they belong everywhere.
        if hints:
            candidates = [
                node for node in candidates
                if node_matches_scope(node.scope or [], hints, project_root=project_root)
            ]
            if not candidates:
                scope_text = ", ".join(hints)
                return {
                    "count": 0,
                    "full_count": 0,
                    "brief_count": 0,
                    "scope": hints,
                    "formatted": (
                        f"════ PROJECT BRIEFING · generated {date_str} ════\n\n"
                        f"(No active memories are scoped to [{scope_text}].)\n"
                        "Scope filters memories; other subsystems are excluded by design.\n"
                        "Retry without scope_hint to brief on the whole workspace.\n"
                        "═══════════════════════════════════════════════════════"
                    ),
                    "full": [],
                    "brief": {},
                }

        scored_candidates: List[Tuple[float, MemoryNode, Features]] = []
        for node in candidates:
            features = cls.compute_node_features(
                node=node,
                now_ts=now_ts,
                authority=authority_scores.get(node.id, 0.0),
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
            map_line,
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
            "scope": hints,
            "project": str(project_root) if project_root else None,
            "formatted": briefing_text,
            "full": [item.node.to_dict() for item in full_tier],
            "brief": {tag: [item.node.to_dict() for item in items] for tag, items in brief_tier.items()},
        }
