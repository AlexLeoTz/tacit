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
                    "description": "Parent memory IDs that this memory causally derives from or supersedes.",
                },
                "related": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Non-causal related memory IDs.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name or project root path. If omitted, uses current workspace.",
                },
            },
            "required": ["content"],
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
        "description": "Generate an institutional project memory summary (decisions, architecture, hacks, errors) to bootstrap context in a new agent session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "enum": ["session", "week", "month", "all"],
                    "default": "week",
                    "description": "Timeframe scope for contextual memory retrieval.",
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
