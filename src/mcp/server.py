"""MCP Server implementation for Tacit using FastMCP with Multi-Project Support."""

import json
from typing import Any, Dict, List, Optional

from ..core.storage import MemoryStorage
from .handlers import MemoryMCPHandlers


def create_mcp_server(storage: Optional[MemoryStorage] = None):
    """Factory creating a configured FastMCP server instance supporting multiple projects."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("tacit")
    handlers = MemoryMCPHandlers(storage)

    @mcp.tool()
    def memory_add(
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
        project: Optional[str] = None,
    ) -> str:
        """Add a persistent memory entry (decision, command, hack, architecture, error, context) to target project.

        If replacing an outdated decision or hack, pass `supersedes=['<previous-node-id>']`.
        """
        res = handlers.handle_memory_add(
            content=content,
            type=type,
            summary=summary,
            title=title,
            tags=tags or [],
            scope=scope or [],
            impact=impact,
            parents=parents or [],
            supersedes=supersedes or [],
            related=related or [],
            author=author,
            relation_note=relation_note,
            project=project,
        )
        return res.get("message") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_search(
        query: str,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        project: Optional[str] = None,
    ) -> str:
        """Search memory entries using full-text index with optional category or tag filtering."""
        res = handlers.handle_memory_search(
            query=query,
            type=type,
            tags=tags,
            limit=limit,
            project=project,
        )
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_get(node_id: str, project: Optional[str] = None) -> str:
        """Retrieve full details of a specific memory entry by UUID."""
        res = handlers.handle_memory_get(node_id=node_id, project=project)
        return res.get("formatted") or res.get("message") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_recent(days: int = 7, limit: int = 20, project: Optional[str] = None) -> str:
        """Get chronological recent memories created in the last N days."""
        res = handlers.handle_memory_recent(days=days, limit=limit, project=project)
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_context(
        timeframe: str = "all",
        budget: Optional[int] = None,
        scope_hint: Optional[List[str]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Generate a relevance-ranked, token-budgeted project briefing based on DAG centrality, impact, and recency decay."""
        res = handlers.handle_memory_context(
            timeframe=timeframe,
            budget=budget,
            scope_hint=scope_hint,
            project=project,
        )
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_projects() -> str:
        """List all discovered project memory workspaces on this machine and their memory counts."""
        res = handlers.handle_memory_projects()
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.prompt("tacit-instructions")
    def tacit_instructions() -> str:
        """System instructions for AI agents on how to use Tacit."""
        return (
            "You are equipped with Tacit tools for maintaining persistent institutional memory.\n"
            "Follow these strict architectural protocols:\n\n"
            "1. SESSION BOOTSTRAP: At the start of a session or when exploring a codebase area, call `memory_context()` "
            "to receive an intelligent relevance-ranked briefing of active architectural patterns, critical commands, hacks, and solved errors.\n\n"
            "2. TAXONOMY & CAUSAL LINEAGE: When calling `memory_add`, always provide:\n"
            "   - `tags`: At least 2 specific keywords (e.g. ['auth', 'jwt', 'security']).\n"
            "   - `scope`: Subsystem or directory path affected (e.g. ['/api/auth']).\n"
            "   - `parents`: Link the UUID(s) of any past decisions from `memory_context` that this new entry modifies, extends, or is derived from.\n"
            "   - `supersedes`: Link the UUID(s) of any previous decisions that this change directly invalidates or replaces.\n\n"
            "3. END-OF-TASK SELF-REFLECTION: At the conclusion of any non-trivial coding task, ask yourself:\n"
            "   'Did I make a key architectural choice, establish a reusable command, implement a tricky bugfix, or apply/invalidate a workaround?'\n"
            "   - If YES, record it using `memory_add`. If invalidating past guidance, include `supersedes=[<id>]`.\n"
            "   - If NO (e.g., minor typo/formatting), do not add noise to memory.\n\n"
            "4. TARGETED SEARCH: Use `memory_search` to query past decisions before introducing new libraries, databases, or schemas."
        )

    return mcp


class MemoryMCPServer:
    """Wrapper for running FastMCP server."""

    def __init__(self, storage: Optional[MemoryStorage] = None):
        self.storage = storage
        self.mcp = create_mcp_server(storage)

    def run(self, transport: str = "stdio") -> None:
        """Run the FastMCP server."""
        if transport == "stdio":
            self.mcp.run(transport="stdio")
        elif transport == "sse":
            self.mcp.run(transport="sse")
        else:
            raise ValueError(f"Unsupported transport: {transport}")
