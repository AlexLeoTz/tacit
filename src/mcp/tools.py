"""Tool definitions and JSON Schema specifications for Tacit MCP server with Multi-Project support."""

from typing import Any, Dict, List

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "memory_add",
        "description": "Persist a new immutable memory node (decision, command, hack, architecture, error, or context) to surviving project storage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full detailed description, rationale, or code snippet of the memory.",
                },
                "type": {
                    "type": "string",
                    "enum": ["decision", "command", "hack", "architecture", "error", "context"],
                    "default": "decision",
                    "description": "Categorical classification of the memory entry.",
                },
                "summary": {
                    "type": "string",
                    "description": "Concise 1-sentence summary of the memory entry.",
                },
                "title": {
                    "type": "string",
                    "description": "Short descriptive title for indexing.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords and tags for taxonomy (e.g. ['auth', 'jwt', 'security']).",
                },
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Affected modules or file paths.",
                },
                "impact": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "default": "medium",
                    "description": "Project impact level.",
                },
                "parents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Parent memory IDs that this memory causally derives from.",
                },
                "supersedes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Memory IDs that this new entry directly invalidates, supersedes, or replaces.",
                },
                "related": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Non-causal related memory IDs.",
                },
                "relation_note": {
                    "type": "string",
                    "description": "Optional explanation for why this memory supersedes or derives from its parents.",
                },
                "category": {
                    "type": "string",
                    "description": "Alias for 'type' (e.g. 'decision', 'hack', 'architecture').",
                },
                "rationale": {
                    "type": "string",
                    "description": "Alias for 'content' explaining technical rationale.",
                },
                "description": {
                    "type": "string",
                    "description": "Alias for 'content'.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or project root path. If omitted, uses current workspace.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "memory_search",
        "description": "Search the persistent memory store via SQLite full-text index with optional category filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search query (e.g. 'JWT auth migration' or 'docker build failure').",
                },
                "type": {
                    "type": "string",
                    "enum": ["decision", "command", "hack", "architecture", "error", "context"],
                    "description": "Optional category filter.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags to filter by.",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of memory results to return.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "keyword"],
                    "default": "hybrid",
                    "description": "Search mode: 'hybrid' (BM25 + dense vector RRF) or 'keyword' (BM25 only).",
                },
                "scope_hint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Active file paths or module paths to prioritize relevance via scope boosting.",
                },
                "include_superseded": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to include superseded or historical memories in search results.",
                },
                "debug": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return BM25 and vector rank provenance for search tuning.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or root path.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_get",
        "description": "Retrieve full details, content, tags, and lineage of a specific memory entry by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The unique UUID of the memory node.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or root path.",
                },
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "memory_recent",
        "description": "Get chronological recent memories created within the past N days.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of past days to query.",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of recent entries to return.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or root path.",
                },
            },
        },
    },
    {
        "name": "memory_context",
        "description": "Generate a relevance-ranked, token-budgeted project briefing (decisions, architecture, hacks, errors) based on DAG centrality, impact, and recency decay to bootstrap agent context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "budget": {
                    "type": "integer",
                    "default": 2000,
                    "description": "Token budget cap for the assembled briefing.",
                },
                "scope_hint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional open file paths or active modules to bias ranking.",
                },
                "timeframe": {
                    "type": "string",
                    "default": "all",
                    "description": "Optional timeframe parameter for backward compatibility.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or root path.",
                },
            },
        },
    },
    {
        "name": "memory_projects",
        "description": "List all discovered and registered project memory workspaces and their memory counts on this machine.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]
