"""MCP Server implementation for Project Memory Cortex using FastMCP with Multi-Project Support."""

import json
from typing import Any, Dict, List, Optional

from ..core.storage import MemoryStorage
from .handlers import MemoryMCPHandlers


def create_mcp_server(storage: Optional[MemoryStorage] = None):
    """Factory creating a configured FastMCP server instance supporting multiple projects."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("project-memory-cortex")
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
        related: Optional[List[str]] = None,
        author: str = "ai-agent",
        project: Optional[str] = None,
    ) -> str:
        """Add a persistent memory entry (decision, command, hack, architecture, error, context) to target project."""
        res = handlers.handle_memory_add(
            content=content,
            type=type,
            summary=summary,
            title=title,
            tags=tags or [],
            scope=scope or [],
            impact=impact,
            parents=parents or [],
            related=related or [],
            author=author,
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
    def memory_context(timeframe: str = "week", project: Optional[str] = None) -> str:
        """Aggregate institutional project memory context (decisions, architecture, hacks, errors) for agent bootstrapping."""
        res = handlers.handle_memory_context(timeframe=timeframe, project=project)
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_projects() -> str:
        """List all discovered project memory workspaces on this machine and their memory counts."""
        res = handlers.handle_memory_projects()
        return res.get("formatted") or json.dumps(res, indent=2)

    @mcp.prompt("project-memory-instructions")
    def project_memory_instructions() -> str:
        """System instructions for AI agents on how to use Project Memory Cortex."""
        return (
            "You are equipped with Project Memory Cortex tools to maintain persistent project memory.\n"
            "1. At session start, call `memory_context` to review past architectural decisions, hacks, and errors.\n"
            "2. Whenever you make an architectural decision, discover a bug, solve a tricky error, or run a setup command, "
            "immediately call `memory_add` with the appropriate type (decision, architecture, hack, command, error).\n"
            "3. Use `memory_search` whenever you need past context on a topic or component."
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
