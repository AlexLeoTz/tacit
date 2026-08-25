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

        CONTENT REQUIREMENT: Provide a comprehensive, self-contained Markdown explanation with technical rationale,
        alternatives considered, root causes, or trade-offs. Do NOT write shallow 2-3 line summaries in content.
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
            parents=parents,
            supersedes=supersedes,
            related=related or [],
            author=author,
            relation_note=relation_note,
            project=project,
        )
        return res.get("message") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_add_batch(
        entries: List[Dict[str, Any]],
        project: Optional[str] = None,
    ) -> str:
        """Record multiple memory entries atomically in a single call (e.g. recording both an 'error' and the subsequent 'decision' or 'hack').

        Entries can reference previous entries in the same batch using `$prev` or index placeholders `$0`, `$1` in `parents`, `supersedes`, or `related`.
        Each entry must contain rich, detailed Markdown `content`.
        """
        res = handlers.handle_memory_add_batch(entries=entries, project=project)
        return res.get("message") or json.dumps(res, indent=2)

    @mcp.tool()
    def memory_search(
        query: str,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        mode: str = "hybrid",
        scope_hint: Optional[List[str]] = None,
        include_superseded: bool = False,
        debug: bool = False,
        project: Optional[str] = None,
    ) -> str:
        """Search memory entries using hybrid BM25 / dense vector search with RRF fusion."""
        res = handlers.handle_memory_search(
            query=query,
            type=type,
            tags=tags,
            limit=limit,
            mode=mode,
            scope_hint=scope_hint,
            include_superseded=include_superseded,
            debug=debug,
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
    def memory_link(
        child_id: str,
        parent_id: str,
        relation: str = "derives_from",
        reason: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """Connect two memory nodes in the causal DAG (relation: 'derives_from', 'supersedes', or 'related').
        
        Use this when an orphan memory node was created or when resolving an error with a decision.
        """
        res = handlers.handle_memory_link(
            child_id=child_id,
            parent_id=parent_id,
            relation=relation,
            reason=reason,
            project=project,
        )
        return res.get("message") or json.dumps(res, indent=2)

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
            "WHAT TACIT STORES VS WHAT NOT TO STORE:\n"
            "- ONLY store distilled tacit knowledge: non-obvious design choices, undocumented workarounds (hacks), specific environment dependencies, critical operational commands, and resolved error caveats.\n"
            "- NEVER store raw chat history/transcripts, terminal logs, or full source code files/snippets. Tacit is an institutional decision ledger, not a code or log sink.\n\n"
            "RIGOROUS CONTENT DETAIL REQUIREMENT:\n"
            "- Never write shallow 1-3 line entries. `summary` is a 1-sentence abstract, but `content` MUST be a rich, self-contained Markdown explanation so any future reader or agent understands the full rationale without asking again:\n"
            "  * FOR DECISIONS / ARCHITECTURE: Include 1) Context & Problem Statement, 2) Alternatives Considered & Why Rejected, 3) Technical Rationale & Strategy, 4) Trade-offs & Operational Consequences, 5) Validation / Verification.\n"
            "  * FOR ERRORS: Include 1) Exact Symptom & Failure Trigger, 2) Root Cause Analysis (why it failed at the code/system level), 3) Resolution / Fix Applied, 4) Prevention & Regression Caveats.\n"
            "  * FOR HACKS: Include 1) Workaround Description, 2) Why the Clean / Native Solution Failed, 3) Known Side Effects, 4) Conditions for Removal / Cleanup.\n"
            "  * FOR COMMANDS: Include 1) Exact Command Syntax & Environment Prerequisites, 2) Expected Side Effects, 3) When to Run vs When NOT to Run.\n\n"
            "MULTI-ENTRY BATCH RECORDING:\n"
            "- If a task involved diagnosing an error and implementing an architectural decision or workaround, record BOTH entries (e.g. record the `error` node and the corresponding `decision`/`hack` node).\n"
            "- Use `memory_add_batch` to insert multiple related entries at once. Use `$prev` or `$0` in `parents` so the decision links to the error it resolves.\n\n"
            "MANDATORY AGENT WORKFLOW:\n"
            "1. SESSION BOOTSTRAP: At session start or when beginning a new task, call `memory_context()` "
            "to receive an intelligent relevance-ranked briefing of active architectural patterns, critical commands, hacks, and solved errors.\n\n"
            "2. PRE-DECISION VALIDATION: Before proposing, planning, or implementing any architectural change, library addition, refactor, or configuration change, you MUST search Tacit (`memory_search` or `memory_context`) to verify whether that decision is allowed, if specific constraints apply, or if that approach was previously tried and invalidated.\n\n"
            "3. TAXONOMY & CAUSAL LINEAGE: When calling `memory_add` or `memory_add_batch`, always provide:\n"
            "   - `tags`: At least 2 specific keywords (e.g. ['auth', 'jwt', 'security']).\n"
            "   - `scope`: Subsystem or directory path affected (e.g. ['/api/auth']).\n"
            "   - `parents`: Link the UUID(s) of any past decisions from `memory_context` that this new entry modifies, extends, or is derived from.\n"
            "   - `supersedes`: Link the UUID(s) of any previous decisions that this change directly invalidates or replaces.\n\n"
            "4. END-OF-TASK SELF-REFLECTION: At the conclusion of any non-trivial coding task, ask yourself:\n"
            "   'Did I solve a non-trivial error, establish an architectural pattern, execute an essential command, or apply/invalidate a workaround?'\n"
            "   - If YES, record rich entries using `memory_add` or `memory_add_batch`. If invalidating past guidance, include `supersedes=[<id>]`.\n"
            "   - If NO (e.g., minor typo/formatting), do not add noise to memory."
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
