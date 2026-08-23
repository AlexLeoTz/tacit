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
        related: Optional[List[str]] = None,
        author: str = "ai-agent",
        metadata: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and store an immutable memory node in target project storage."""
        storage = self._resolve_storage(project)
        tags = tags or []
        scope = scope or []
        parents = parents or []
        related = related or []
        metadata = metadata or {}

        # Pre-flight check: If agent didn't provide parents, check for existing similar memories
        linked_hint = ""
        if not parents:
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

        success = storage.add_memory(node)
        proj_label = f" (Project: {project})" if project else ""
        if success:
            return {
                "success": True,
                "id": node.id,
                "summary": node.summary,
                "type": node.type,
                "parents": parents,
                "content_hash": node.content_hash,
                "message": f"Memory recorded [{node.type}]{proj_label}: {node.summary} (ID: {node.id}){linked_hint}",
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
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search memories via full text index and filters in target project."""
        storage = self._resolve_storage(project)
        fts = FullTextSearch(storage)
        results = fts.search(query=query, limit=limit, memory_type=type, tags=tags)
        if not results:
            proj_hint = f" in project '{project}'" if project else ""
            return {
                "count": 0,
                "results": [],
                "formatted": f"No memory entries found matching query: '{query}'{proj_hint}",
            }

        formatted_lines = [f"Found {len(results)} memory entries for '{query}':\n"]
        items = []
        for node in results:
            date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
            tags_str = f" [tags: {', '.join(node.tags)}]" if node.tags else ""
            formatted_lines.append(f"- [{date_str}] ({node.type.upper()}) {node.title or node.summary}")
            formatted_lines.append(f"  Summary: {node.summary}")
            formatted_lines.append(f"  ID: `{node.id}`{tags_str}\n")

            items.append({
                "id": node.id,
                "timestamp": node.timestamp,
                "type": node.type,
                "title": node.title,
                "summary": node.summary,
                "tags": node.tags,
                "impact": node.impact,
            })

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

        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        formatted = f"""==================================================
MEMORY NODE: {node.id}
Type: {node.type.upper()} | Impact: {node.impact.upper()} | Status: {node.status}
Recorded: {date_str} by {node.author}
Title: {node.title}
==================================================

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
        self, timeframe: str = "week", project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Aggregate structured memory context for agent session initialization."""
        storage = self._resolve_storage(project)
        temporal = TemporalSearch(storage)
        memories = temporal.get_by_timeframe(timeframe=timeframe, limit=100)
        if not memories:
            return {
                "count": 0,
                "timeframe": timeframe,
                "formatted": f"# Project Institutional Memory\n\nNo recent memories found for timeframe '{timeframe}'.",
            }

        grouped = temporal.group_by_type(memories)
        lines = [f"# Project Institutional Memory (Timeframe: {timeframe.capitalize()})\n"]

        category_order = ["decision", "architecture", "hack", "error", "command", "context"]
        for cat in category_order:
            nodes = grouped.get(cat, [])
            if nodes:
                lines.append(f"\n## {cat.capitalize()}s ({len(nodes)})")
                for node in nodes[:5]:
                    lines.append(f"- **{node.title or node.summary}**: {node.summary} [`{node.id[:8]}`]")

        return {
            "count": len(memories),
            "timeframe": timeframe,
            "formatted": "\n".join(lines),
        }

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
