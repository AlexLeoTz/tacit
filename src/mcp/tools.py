"""Tool definitions and JSON Schema specifications for Tacit MCP server with Multi-Project support."""

from typing import Any, Dict, List

from ..utils.config import Config

#: Derived from the single taxonomy definition so the schemas can never drift
#: from ``Config.MEMORY_TYPES``.
MEMORY_TYPES: List[str] = list(Config.MEMORY_TYPES)
DEFAULT_MEMORY_TYPE: str = Config.DEFAULT_MEMORY_TYPE
MEMORY_TYPE_HINT = ", ".join(MEMORY_TYPES)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "memory_add",
        "description": f"Persist a new immutable memory node to surviving project storage. One of: {MEMORY_TYPE_HINT}. The content field must be rich and comprehensive.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full detailed Markdown description with technical rationale, root causes, alternatives, or trade-offs. Never provide shallow 1-2 line summaries here.",
                },
                "type": {
                    "type": "string",
                    "enum": MEMORY_TYPES,
                    "default": DEFAULT_MEMORY_TYPE,
                    "description": "Categorical classification of the memory entry.",
                },
                "summary": {
                    "type": "string",
                    "description": "Concise 1-sentence summary of the memory entry.",
                },
                "title": {
                    "type": "string",
                    "description": "REQUIRED. Specific, self-contained title that names the subject (e.g. 'Replaced Redis sessions with signed JWT cookies'). This is embedded into the vector index together with the summary, so a vague title ('auth fix') makes the memory unfindable by semantic search. Do not start with the category name.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords and tags for taxonomy (e.g. ['auth', 'jwt', 'security']).",
                },
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Affected modules or file paths, relative to the project root. Required in practice: scope is the filter later reads apply, so a memory recorded against the wrong path can never be found again. Use the project name for knowledge that applies to the whole workspace. Paths are validated and a non-existent path is rejected.",
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
                "project": {
                    "type": "string",
                    "description": "Workspace to write to: absolute project root path or registered name. Pass your own workspace root.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_add_batch",
        "description": "Persist multiple related memory entries in a single batch (e.g. recording both an 'error' and the subsequent 'decision' or 'hack'). Entries can reference earlier batch items using '$prev' or '$0' in parents/supersedes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Comprehensive Markdown explanation."},
                            "type": {"type": "string", "enum": MEMORY_TYPES, "default": DEFAULT_MEMORY_TYPE},
                            "summary": {"type": "string", "description": "1-sentence summary."},
                            "title": {"type": "string", "description": "REQUIRED. Specific, self-contained title; embedded into the vector index."},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "scope": {"type": "array", "items": {"type": "string"}},
                            "impact": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
                            "parents": {"type": "array", "items": {"type": "string"}, "description": "Parent IDs or intra-batch references like '$prev' or '$0'."},
                            "supersedes": {"type": "array", "items": {"type": "string"}},
                            "related": {"type": "array", "items": {"type": "string"}},
                            "relation_note": {"type": "string"},
                        },
                        "required": ["content", "title"],
                    },
                    "description": "List of memory entries to record in order.",
                },
            },
            "required": ["entries"],
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
                    "enum": MEMORY_TYPES,
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
                    "description": "Optional. Project-relative paths you are working on (e.g. 'src/api'). Scope is a FILTER: only memories scoped to these paths (plus project-wide knowledge) are returned. Omit it to read the whole workspace. Absolute paths outside the project are ignored.",
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
                    "description": "Workspace to read: an absolute path to the project root (or a registered project name). Pass your own workspace root; without it the server falls back to the workspace it was launched in.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_get",
        "description": "Retrieve full details, content, tags, and lineage of one specific memory by its complete UUID. Exact match only -- find the id first with memory_grep or memory_search, which both print full UUIDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The complete UUID of the memory node (not a prefix).",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to read from: absolute project root path or registered name.",
                },
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "memory_grep",
        "description": "Find memories whose TITLE or SUMMARY contains a keyword, as a plain case-insensitive substring. Not semantic and does not read content: exact, instant, and requires no embedding model, so it works when the embedding provider is unavailable. Use it to locate a known phrase, symbol or component name; use memory_search for meaning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Substring to look for in titles and summaries (e.g. 'pgvector', 'WinError 32').",
                },
                "type": {
                    "type": "string",
                    "enum": MEMORY_TYPES,
                    "description": "Optional category filter.",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum number of matches to return.",
                },
                "include_superseded": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include memories that have been superseded.",
                },
                "scope_hint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Project-relative paths to filter matches by; project-wide memories always match.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to search: absolute project root path or registered name.",
                },
            },
            "required": ["keyword"],
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
                "scope_hint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Project-relative paths to filter by.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to read: absolute project root path or registered name.",
                },
            },
        },
    },
    {
        "name": "memory_context",
        "description": "Generate a token-budgeted project briefing ranked by PageRank authority (how many later memories trace back to it), with impact and recency as bounded tie-breakers. Use at session start to load institutional context.",
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
                    "description": "Optional. Project-relative paths to filter the briefing by: only memories scoped to these paths (plus project-wide knowledge) are shown. Omit it to brief on the whole workspace.",
                },
                "timeframe": {
                    "type": "string",
                    "default": "all",
                    "description": "Filter which memories may appear: 'all', 'week', '30d', '6h', 'year', or an ISO date. Ranking still uses the whole graph.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to brief on: absolute project root path or registered name. Pass your own workspace root.",
                },
            },
        },
    },
    {
        "name": "memory_link",
        "description": "Connect two memory nodes in the causal DAG (relation: 'derives_from', 'supersedes', or 'related'). Use it when a memory was recorded as an orphan, or when a diagnosis resolves a specific earlier error.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "child_id": {
                    "type": "string",
                    "description": "Complete UUID of the child (the newer / deriving memory).",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Complete UUID of the parent (the memory it derives from, supersedes, or relates to).",
                },
                "relation": {
                    "type": "string",
                    "enum": ["derives_from", "supersedes", "related"],
                    "default": "derives_from",
                    "description": "Edge type to create.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the edge exists; stored with it and shown in lineage output.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace both nodes live in: absolute project root path or registered name.",
                },
            },
            "required": ["child_id", "parent_id"],
        },
    },
    {
        "name": "memory_chronicle",
        "description": "Return the project's ENTIRE memory history in chronological order (oldest first), for deep analysis of how the project got here. Nothing is ranked, budgeted or deduped, and superseded decisions are included. Use brief=true for a one-line-per-memory timeline and limit=0 for everything.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_hint": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Project-relative paths to filter the timeline by (project-wide memories always included).",
                },
                "type": {
                    "type": "string",
                    "enum": MEMORY_TYPES,
                    "description": "Only include this memory category.",
                },
                "timeframe": {
                    "type": "string",
                    "default": "all",
                    "description": "Only include memories from this window: 'all', 'week', '30d', '6h', 'year', or an ISO date.",
                },
                "limit": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum memories to render; 0 means the entire history.",
                },
                "brief": {
                    "type": "boolean",
                    "default": False,
                    "description": "One line per memory instead of full content.",
                },
                "include_superseded": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include memories that were later superseded (default true: they are part of the reasoning history).",
                },
                "include_retracted": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also include memories that were retracted as wrong.",
                },
                "content_chars": {
                    "type": "integer",
                    "default": 4000,
                    "description": "Elide each memory's content beyond this many characters; 0 never elides.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to read: absolute project root path or registered name.",
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
    {
        "name": "project_structure",
        "description": "Return the workspace STRUCTURE map: directories and file names only, never source code, annotated with any stored per-file gists. Call once at session start to learn where things live instead of exploring file by file. `refresh=true` re-walks the filesystem when files were added or renamed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Re-walk the filesystem and update the stored snapshot before rendering.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional project-relative subdirectory (or file) to narrow the map to.",
                },
                "include_gists": {
                    "type": "boolean",
                    "default": True,
                    "description": "Annotate files with their stored one-line gists.",
                },
                "max_lines": {
                    "type": "integer",
                    "default": 400,
                    "description": "Cap on rendered lines, so a huge workspace cannot flood the context.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace whose map to render: absolute project root path or registered name.",
                },
            },
        },
    },
    {
        "name": "project_files_pending",
        "description": "List the files whose table row is missing or stale, with line counts, sizes and languages already computed. Write the descriptions it asks for in ONE project_files_update call (many entries at once) rather than one call per file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 25,
                    "description": "Maximum number of files to list.",
                },
                "include_facts": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include the computed line count, size and language per file.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to read: absolute project root path or registered name.",
                },
            },
        },
    },
    {
        "name": "project_files_update",
        "description": "Write many file-table rows in one call: each entry is {'path': 'backend/app/Payment.php', 'description': 'contains the payment logic: gateway calls, refunds, receipts'}. Tacit records line count, size, content hash, author and timestamp itself. A missing path is rejected per entry without losing the rest of the batch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "description": {"type": "string"},
                            "by": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                    "description": "Rows to write; each needs a project-relative path and a compact description.",
                },
                "by": {
                    "type": "string",
                    "default": "ai-agent",
                    "description": "Who is writing these rows; recorded per row.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace to write to: absolute project root path or registered name.",
                },
            },
            "required": ["entries"],
        },
    },
    {
        "name": "project_gist",
        "description": "Record a file-table row for ONE file: a one-line description of what it contains, shown beside that file in project_structure. Pass an empty gist to clear it. For many files, use project_files_pending + project_files_update.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Project-relative path of the file the description is about (e.g. 'backend/app/Models/Film.php'). Must exist.",
                },
                "gist": {
                    "type": "string",
                    "description": "One informative sentence about the file's contents or role. Empty clears it.",
                },
                "author": {
                    "type": "string",
                    "default": "ai-agent",
                    "description": "Who recorded it; stored on the row with the timestamp.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace the file belongs to: absolute project root path or registered name.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_pin",
        "description": "Pin or unpin memories so they always appear at the end of memory_context regardless of their score. Pinned memories represent important tacit knowledge and critical invariants curated by developers that agents must always pay attention to.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of memory IDs (UUIDs) to pin or unpin.",
                },
                "unpin": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, unpin the specified memories instead of pinning them.",
                },
                "project": {
                    "type": "string",
                    "description": "Workspace: absolute project root path or registered name.",
                },
            },
            "required": ["ids"],
        },
    },
]
