"""Tool execution handlers for Model Context Protocol (MCP) integrations with Multi-Project support."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage
from ..search.full_text import FullTextSearch
from ..search.temporal import TemporalSearch
from ..utils.config import Config


class MemoryMCPHandlers:
    """Core handler logic for Tacit MCP tools supporting multiple projects."""

    def __init__(self, default_storage: Optional[MemoryStorage] = None):
        self._storage_cache: Dict[str, MemoryStorage] = {}
        if default_storage:
            self._default_storage = default_storage
            # Cache default storage under its db path
            self._storage_cache[str(default_storage.db_path.resolve())] = default_storage
        else:
            self._default_storage = None

    def _resolve_storage(self, project: Optional[str] = None) -> MemoryStorage:
        """Resolve or initialize SQLite storage for a given project path or active workspace."""
        if project:
            registered = Config.list_registered_projects()
            target_path_str = registered.get(project, project)
            project_root = Config.find_project_root(target_path_str)
        elif self._default_storage:
            return self._default_storage
        else:
            project_root = Config.find_project_root()

        key = str(project_root.resolve())
        if key not in self._storage_cache:
            Config.ensure_directories(project_root)
            db_path = Config.get_db_path(project_root)
            self._storage_cache[key] = MemoryStorage(db_path)

        return self._storage_cache[key]

    def handle_memory_add(
        self,
        content: str,
        type: str = "decision",
        summary: str = "",
        title: str = "",
        tags: Optional[List[str]] = None,
        scope: Optional[List[str]] = None,
        impact: str = "medium",
        parents: Optional[List[str]] = None,
        supersedes: Optional[List[str]] = None,
        related: Optional[List[str]] = None,
        author: str = "ai-agent",
        relation_note: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and store an immutable memory node in target project storage."""
        storage = self._resolve_storage(project)
        tags = tags or []
        scope = scope or []
        parents = parents or []
        supersedes = supersedes or []
        related = related or []
        metadata = metadata or {}

        # Pre-flight check: If agent didn't provide parents, check for existing similar memories
        linked_hint = ""
        if not parents and not supersedes:
            pre_flight_query = title or summary or content[:100]
            existing_matches = storage.search_full_text(query=pre_flight_query, limit=3, memory_type=type)
            if existing_matches:
                top_match = existing_matches[0]
                # If top match is highly relevant, link it as parent
                parents = [top_match.id]
                linked_hint = f" (Auto-linked to related ancestor: '{top_match.title or top_match.summary}' [`{top_match.id[:8]}`])"

        # Validate scope paths exist in target project root
        from ..core.memory_node import validate_scope_paths
        validate_scope_paths(scope, project)

        node = MemoryNode(
            id=str(uuid.uuid4()),
            timestamp=datetime.now().astimezone().timestamp(),
            content=content,
            summary=summary or (content[:100] + ("..." if len(content) > 100 else "")),
            title=title or f"{type.capitalize()}: {content[:50]}",
            type=type,
            tags=tags,
            scope=scope,
            impact=impact,
            parents=parents,
            related=related,
            author=author,
            metadata=metadata,
        )

        success = storage.add_memory(
            node,
            supersedes=supersedes if supersedes else None,
            relation_reason=relation_note,
        )
        proj_label = f" (Project: {project})" if project else ""
        sup_label = f" [Supersedes: {', '.join(f'`{s[:8]}`' for s in supersedes)}]" if supersedes else ""
        if success:
            return {
                "success": True,
                "id": node.id,
                "summary": node.summary,
                "type": node.type,
                "parents": parents,
                "supersedes": supersedes,
                "content_hash": node.content_hash,
                "message": f"Memory recorded [{node.type}]{proj_label}{sup_label}: {node.summary} (ID: {node.id}){linked_hint}",
            }
        else:
            return {
                "success": False,
                "id": node.id,
                "message": f"Failed to record memory{proj_label}: duplicate or integrity error.",
            }

    def handle_memory_search(
        self,
        query: str,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        mode: str = "hybrid",
        scope_hint: Optional[List[str]] = None,
        include_superseded: bool = False,
        debug: bool = False,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search memories via hybrid FTS5/dense vector engine with RRF fusion."""
        storage = self._resolve_storage(project)
        results = storage.search_hybrid(
            query=query,
            limit=limit,
            mode=mode,
            scope_hint=scope_hint,
            memory_type=type,
            tags=tags,
            include_superseded=include_superseded,
            debug=debug,
        )
        if not results:
            proj_hint = f" in project '{project}'" if project else ""
            return {
                "count": 0,
                "results": [],
                "formatted": f"No memory entries found matching query: '{query}'{proj_hint}",
            }

        formatted_lines = [f"Found {len(results)} memory entries for '{query}':\n"]
        items = []
        for item in results:
            node = item["node"]
            score = item.get("score", 0.0)
            date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
            tags_str = f" [tags: {', '.join(node.tags)}]" if node.tags else ""
            prov_str = ""
            if debug and "provenance" in item:
                p = item["provenance"]
                prov_str = f" [bm25_rank: {p.get('bm25_rank')}, vec_rank: {p.get('vec_rank')}]"

            status_flag = f" [{node.status.upper()}]" if node.status != "active" else ""
            formatted_lines.append(f"- [{date_str}] ({node.type.upper()}){status_flag} {node.title or node.summary}")
            formatted_lines.append(f"  Summary: {node.summary}")
            formatted_lines.append(f"  ID: `{node.id}` (Score: {score:.3f}){tags_str}{prov_str}\n")

            entry: Dict[str, Any] = {
                "id": node.id,
                "timestamp": node.timestamp,
                "type": node.type,
                "title": node.title,
                "summary": node.summary,
                "tags": node.tags,
                "impact": node.impact,
                "status": node.status,
                "score": score,
            }
            if debug and "provenance" in item:
                entry["provenance"] = item["provenance"]
            items.append(entry)

        return {
            "count": len(results),
            "results": items,
            "formatted": "\n".join(formatted_lines),
        }

    def handle_memory_get(self, node_id: str, project: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve full details of a single memory by ID in target project with full lineage tree."""
        from ..core.memory_dag import MemoryDAG

        storage = self._resolve_storage(project)
        node = storage.get_memory(node_id)
        if not node:
            return {
                "found": False,
                "message": f"Memory node with ID '{node_id}' was not found.",
            }

        # Build lineage tree
        all_nodes = storage.get_all(limit=1000)
        dag = MemoryDAG()
        for n in sorted(all_nodes, key=lambda x: x.timestamp):
            try:
                dag.add_node(n)
            except Exception:
                pass

        ancestors = [dag.get_node(aid) for aid in dag.get_ancestors(node.id) if dag.get_node(aid)]
        descendants = [dag.get_node(did) for did in dag.get_descendants(node.id) if dag.get_node(did)]

        ancestry_tree_lines = []
        if ancestors:
            ancestry_tree_lines.append("CAUSAL ANCESTORS (Foundations):")
            for a in sorted(ancestors, key=lambda x: x.timestamp):
                ancestry_tree_lines.append(f"  └── [{a.type}] {a.title or a.summary} (`{a.id[:8]}`)")
        else:
            ancestry_tree_lines.append("CAUSAL ANCESTORS: None (Root Decision)")

        if descendants:
            ancestry_tree_lines.append("\nCAUSAL DESCENDANTS (Derived):")
            for d in sorted(descendants, key=lambda x: x.timestamp):
                ancestry_tree_lines.append(f"  └── [{d.type}] {d.title or d.summary} (`{d.id[:8]}`)")
        else:
            ancestry_tree_lines.append("CAUSAL DESCENDANTS: None")

        lineage_block = "\n".join(ancestry_tree_lines)

        # Status alert banner if node is not active
        status_banner = ""
        if node.status == "superseded":
            # Search for successor edge or event
            edges = storage.get_edges()
            successor_edges = [e for e in edges if e.get("parent_id") == node.id and e.get("relation") == "supersedes"]
            if successor_edges:
                succ = successor_edges[0]
                succ_id = succ.get("child_id", "unknown")
                succ_node = storage.get_memory(succ_id)
                succ_title = f' "{succ_node.title or succ_node.summary}"' if succ_node else ""
                reason_str = f': "{succ.get("reason")}"' if succ.get("reason") else ""
                status_banner = f"\n⚠️ SUPERSEDED by {succ_id[:8]}{succ_title}{reason_str}\n(This entry is kept for historical lineage; do NOT treat as active guidance.)\n"
            else:
                status_banner = "\n⚠️ SUPERSEDED: This decision has been superseded by a newer entry.\n"
        elif node.status == "retracted":
            status_banner = "\n⚠️ RETRACTED: This entry was recorded in error or invalidated.\n"

        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        formatted = f"""==================================================
MEMORY NODE: {node.id}
Type: {node.type.upper()} | Impact: {node.impact.upper()} | Status: {node.status.upper()}
Recorded: {date_str} by {node.author}
Title: {node.title}
=================================================={status_banner}
SUMMARY:
{node.summary}

CONTENT:
{node.content}

TAXONOMY & LINEAGE:
Tags: {', '.join(node.tags) if node.tags else 'None'}
Scope: {', '.join(node.scope) if node.scope else 'Global'}
Parents: {', '.join(node.parents) if node.parents else 'None'}
Children: {', '.join(node.children) if node.children else 'None'}
Related: {', '.join(node.related) if node.related else 'None'}

DECISION TREE / CAUSALITY:
{lineage_block}

INTEGRITY:
Content Hash: {node.content_hash}
Merkle Root: {node.merkle_root}
=================================================="""

        return {
            "found": True,
            "memory": node.to_dict(),
            "formatted": formatted,
        }

    def handle_memory_recent(
        self, days: int = 7, limit: int = 20, project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get recent memory items within the specified days in target project."""
        storage = self._resolve_storage(project)
        temporal = TemporalSearch(storage)
        recent = temporal.get_recent(days=days, limit=limit)
        if not recent:
            return {
                "count": 0,
                "results": [],
                "formatted": f"No memory entries recorded in the last {days} days.",
            }

        lines = [f"Recent Memories (Last {days} days - {len(recent)} entries):\n"]
        items = []
        for node in recent:
            date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
            lines.append(f"- [{date_str}] ({node.type}) {node.summary} (ID: `{node.id}`)")
            items.append({
                "id": node.id,
                "timestamp": node.timestamp,
                "type": node.type,
                "summary": node.summary,
            })

        return {
            "count": len(recent),
            "results": items,
            "formatted": "\n".join(lines),
        }

    def handle_memory_context(
        self,
        timeframe: str = "all",
        budget: Optional[int] = None,
        scope_hint: Optional[List[str]] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate relevance-ranked, token-budgeted institutional briefing for agent session bootstrap."""
        from ..core.bootstrap import BootstrapEngine
        storage = self._resolve_storage(project)
        briefing_res = BootstrapEngine.generate_briefing(
            storage=storage,
            budget=budget if budget is not None else Config.TOKEN_BUDGET,
            scope_hint=scope_hint,
        )
        return briefing_res

    def handle_memory_projects(self) -> Dict[str, Any]:
        """List all discovered / registered project workspaces and their memory counts."""
        registered = Config.list_registered_projects()
        current_root = Config.find_project_root()
        registered[current_root.name] = str(current_root.resolve())

        projects_summary = []
        formatted_lines = ["# Registered Projects & Memory Counts\n"]

        for name, path_str in sorted(registered.items()):
            root = Path(path_str)
            db_path = Config.get_db_path(root)
            count = 0
            if db_path.exists():
                try:
                    s = MemoryStorage(db_path)
                    count = s.get_count()
                except Exception:
                    count = 0

            projects_summary.append({
                "name": name,
                "path": path_str,
                "memory_count": count,
                "active": (root == current_root),
            })
            active_marker = " *(active)*" if root == current_root else ""
            formatted_lines.append(f"- **{name}**{active_marker}: `{path_str}` — **{count} memories**")

        return {
            "count": len(projects_summary),
            "projects": projects_summary,
            "formatted": "\n".join(formatted_lines),
        }

    def handle_memory_delete(self, node_id: str, project: Optional[str] = None) -> Dict[str, Any]:
        """Delete a memory node by ID from the project."""
        storage = self._resolve_storage(project)
        deleted = storage.delete_memory(node_id)
        if deleted:
            return {
                "success": True,
                "node_id": node_id,
                "message": f"Memory node `{node_id}` successfully deleted.",
            }
        else:
            return {
                "success": False,
                "node_id": node_id,
                "message": f"Memory node `{node_id}` not found or could not be deleted.",
            }

    def handle_memory_clear(self, project: Optional[str] = None) -> Dict[str, Any]:
        """Clear all memories in a project."""
        storage = self._resolve_storage(project)
        count = storage.clear_all_memories()
        return {
            "success": True,
            "count": count,
            "message": f"Cleared all {count} memories from project storage.",
        }
