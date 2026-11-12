"""The whole history of a project, oldest memory first.

A briefing answers "what matters right now" and is deliberately selective: it is
budgeted, ranked, deduplicated by tag and filtered by scope. A chronicle answers
a different question — *how did this project get here* — and is therefore the
opposite of selective:

* every memory, including ones that were superseded or retracted, because a
  replaced decision is part of the reasoning history;
* oldest first, so it reads as a timeline rather than a ranking;
* no authority weighting, no diversity guard, no token budget arithmetic — the
  caller decides how much it wants with ``limit``/``brief``.

This is the entry point for an agent asked to do a deep review of a codebase's
institutional knowledge, and for a human auditing what Tacit actually holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .memory_node import MemoryNode
from .bootstrap import parse_timeframe
from ..utils.scope import node_matches_scope

#: Content longer than this is elided, so one enormous memory cannot crowd out
#: the rest of the timeline. Raise it with ``content_chars`` when needed.
DEFAULT_CONTENT_CHARS = 4000

#: Default number of memories rendered. ``limit=0`` means "no cap".
DEFAULT_LIMIT = 100


@dataclass
class ChronicleEntry:
    """One memory on the timeline, with its position and parents resolved."""

    index: int
    node: MemoryNode
    parents: List[str]

    @property
    def when(self) -> datetime:
        return datetime.fromtimestamp(self.node.timestamp).astimezone()


class ChronicleEngine:
    """Render the project's complete memory timeline."""

    @classmethod
    def build(
        cls,
        storage: Any,
        scope_hint: Optional[Sequence[str]] = None,
        memory_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        include_superseded: bool = True,
        include_retracted: bool = False,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        brief: bool = False,
        content_chars: int = DEFAULT_CONTENT_CHARS,
        now_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Return the full chronological history as structured data + text.

        ``offset`` pages through the timeline. It exists so the mandatory
        exhaustive-search fallback can hand each of five sub-agents one 20% slice
        of the store instead of every agent reading (or missing) the whole thing.
        """
        now_dt = now_dt or datetime.now(timezone.utc)
        cutoff = parse_timeframe(timeframe, now_dt.timestamp())
        hints = [h.strip() for h in (scope_hint or []) if h and h.strip()]
        offset = max(0, int(offset or 0))

        wants_all = int(limit or 0) <= 0
        page_size = None if wants_all else max(1, int(limit))

        project_root = None
        try:
            from ..utils.config import Config

            project_root = Config.project_root_for_db(storage.db_path)
        except Exception:
            project_root = None

        if hints:
            # Scope is a path-aware filter applied in Python, so paging must load
            # the filtered set before slicing; otherwise OFFSET would count rows
            # that the scope later discards.
            all_nodes = storage.get_chronological(
                include_superseded=include_superseded or include_retracted,
                include_retracted=include_retracted,
                memory_type=memory_type,
                since=cutoff,
            )
            all_nodes = [
                node for node in all_nodes
                if node_matches_scope(node.scope or [], hints, project_root=project_root)
            ]
            total = len(all_nodes)
            page = all_nodes[offset:] if page_size is None else all_nodes[offset:offset + page_size]
        else:
            total = storage.count_chronological(
                include_superseded=include_superseded or include_retracted,
                include_retracted=include_retracted,
                memory_type=memory_type,
                since=cutoff,
            )
            # Fetch one extra row so "there is more" can be reported honestly.
            fetch_limit = None if page_size is None else page_size + 1
            nodes = storage.get_chronological(
                include_superseded=include_superseded or include_retracted,
                include_retracted=include_retracted,
                memory_type=memory_type,
                since=cutoff,
                limit=fetch_limit,
                offset=offset,
            )
            page = nodes[:page_size] if page_size is not None else nodes

        truncated = (offset + len(page)) < total

        entries = [
            ChronicleEntry(index=offset + index, node=node, parents=list(node.parents or []))
            for index, node in enumerate(page, start=1)
        ]

        formatted = cls.render(
            entries,
            scope=hints,
            brief=brief,
            content_chars=content_chars,
            truncated=truncated,
            memory_type=memory_type,
            timeframe=timeframe,
            include_superseded=include_superseded,
            include_retracted=include_retracted,
            offset=offset,
            total=total,
        )

        return {
            "count": len(entries),
            "total": total,
            "offset": offset,
            "truncated": truncated,
            "first": entries[0].node.timestamp if entries else None,
            "last": entries[-1].node.timestamp if entries else None,
            "scope": hints,
            "type": memory_type,
            "timeframe": timeframe,
            "brief": brief,
            "project": str(project_root) if project_root else None,
            "formatted": formatted,
            "entries": [
                {
                    "index": entry.index,
                    "id": entry.node.id,
                    "timestamp": entry.node.timestamp,
                    "type": entry.node.type,
                    "impact": entry.node.impact,
                    "status": entry.node.status,
                    "title": entry.node.title,
                    "summary": entry.node.summary,
                    "scope": list(entry.node.scope or []),
                    "tags": list(entry.node.tags or []),
                    "parents": entry.parents,
                    "content": entry.node.content,
                }
                for entry in entries
            ],
        }

    @classmethod
    def render(
        cls,
        entries: Sequence[ChronicleEntry],
        scope: Optional[Sequence[str]] = None,
        brief: bool = False,
        content_chars: int = DEFAULT_CONTENT_CHARS,
        truncated: bool = False,
        memory_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        include_superseded: bool = True,
        include_retracted: bool = False,
        offset: int = 0,
        total: Optional[int] = None,
    ) -> str:
        filters: List[str] = []
        if memory_type:
            filters.append(f"type={memory_type}")
        if timeframe and timeframe != "all":
            filters.append(f"window={timeframe}")
        if not include_superseded:
            filters.append("active only")
        if include_retracted:
            filters.append("retracted included")
        filter_text = f" · {' · '.join(filters)}" if filters else ""

        if not entries:
            if offset and total:
                return (
                    "════ TACIT CHRONICLE ════\n\n"
                    f"(Offset {offset} is past the end: this timeline has {total} "
                    "memories. Use a smaller offset.)\n"
                    "════════════════════════"
                )
            return (
                "════ TACIT CHRONICLE ════\n\n"
                "(No memories recorded"
                + (f" within scope [{', '.join(scope)}]" if scope else "")
                + filter_text.replace(" · ", " with ")
                + ". This project has no institutional history yet.)\n"
                "════════════════════════"
            )

        first = entries[0].when.strftime("%Y-%m-%d")
        last = entries[-1].when.strftime("%Y-%m-%d")
        page_text = f" · showing {offset + 1}-{offset + len(entries)}"
        if total is not None:
            page_text += f" of {total}"
        header = (
            f"════ TACIT CHRONICLE · {len(entries)} memories · {first} → {last}"
            f"{page_text}{filter_text} ════"
        )
        if scope:
            header += f"\n(scope filter: {', '.join(scope)})"

        lines: List[str] = [header, ""]
        current_month = ""

        for entry in entries:
            when = entry.when
            month = when.strftime("%Y-%m")
            if month != current_month:
                current_month = month
                lines.append(f"── {month} ─────────────────────────────────────────")
                lines.append("")

            age = ""
            lines.append(cls._render_entry(entry, brief=brief, content_chars=content_chars, age=age))
            lines.append("")

        lines.append("════════════════════════")
        if truncated:
            remaining = (total - (offset + len(entries))) if total is not None else None
            if remaining is not None:
                lines.append(
                    f"… {remaining} more memories follow after offset "
                    f"{offset + len(entries)}; this is one chunk, not the whole timeline."
                )
            lines.append(
                "… timeline truncated. Raise `limit` (0 = everything) or pass a "
                "larger `offset` (and the same limit) to continue."
            )
        return "\n".join(lines)

    @classmethod
    def _render_entry(
        cls,
        entry: ChronicleEntry,
        brief: bool,
        content_chars: int,
        age: str = "",
    ) -> str:
        node = entry.node
        when = entry.when.strftime("%Y-%m-%d %H:%M")
        status = f" [{node.status.upper()}]" if node.status and node.status != "active" else ""
        marker = f"[{entry.index:03d}]"

        if brief:
            return (
                f"{marker} {when} · {node.type.upper()}{status} · `{node.id}` · "
                f"{node.title or node.summary}"
            )

        head = (
            f"{marker} {when} · {node.type.upper()} · {node.impact} impact{status}"
            f" · `{node.id}`"
        )
        body: List[str] = [head]
        body.append(f"  {node.title or '(untitled)'}")
        if node.summary:
            body.append(f"  {node.summary}")

        content = (node.content or "").strip()
        if content:
            if content_chars and len(content) > content_chars:
                omitted = len(content) - content_chars
                content = content[:content_chars].rstrip() + f"\n  … [{omitted} chars elided]"
            body.append("")
            body.extend(f"  {line}" if line.strip() else "" for line in content.splitlines())

        facts: List[str] = []
        if node.scope:
            facts.append("scope: " + ", ".join(str(s) for s in node.scope))
        if node.tags:
            facts.append("tags: " + ", ".join(str(t) for t in node.tags))
        if entry.parents:
            facts.append("derives from: " + ", ".join(f"`{p}`" for p in entry.parents))
        supersedes = getattr(node, "supersedes", None) or []
        if supersedes:
            facts.append("supersedes: " + ", ".join(f"`{s}`" for s in supersedes))
        if facts:
            body.append("")
            body.extend(f"  ↳ {fact}" for fact in facts)
        return "\n".join(body)
