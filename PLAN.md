# Implementation Plan: Project Memory Cortex MVP

A persistent, immutable, timestamped project memory system for AI coding agents with a local Model Context Protocol (MCP) server, SQLite+FTS5 storage, DAG relationship tracking, and a live-reloading markdown preview server.

## User Review Required

> [!IMPORTANT]
> **MCP Python SDK Compatibility**:
> We will implement the MCP server using standard Python MCP SDK patterns (`mcp.server.fastmcp.FastMCP` or low-level `Server`) while ensuring clean JSON-RPC stdio and SSE transport support so tools like Claude Desktop, Cursor, and Antigravity can interact with it without friction.
>
> **Python Environment & Dependencies**:
> The project will support modern Python (>=3.10). Key dependencies include `typer`, `rich`, `pydantic`, `mcp`, `websockets`, `markdown`, `python-dotenv`, `watchdog`, and `pytest`.

## Architecture Overview

```mermaid
graph TD
    AI["AI Agent (Claude / Cursor / Antigravity)"] -->|MCP Protocol (stdio/sse)| MCP["MCP Server (src/mcp)"]
    CLI["CLI (Typer + Rich)"] --> Core["Memory Core & DAG (src/core)"]
    MCP --> Core
    Core --> Storage["SQLite + FTS5 & File Storage"]
    Core --> Search["Search Engine (FTS5 + Temporal + Bloom)"]
    Storage --> Exporter["Markdown Exporter (src/export)"]
    Exporter --> Preview["Live Preview Server (HTTP + WebSockets)"]
    Preview --> Browser["Browser UI (Live Markdown)"]
```

---

## Proposed Changes

### 1. Configuration & Utilities (`src/utils/`)

#### [NEW] [config.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/utils/config.py)
- Configuration loader for database paths, preview ports, export paths, and search limit defaults using `python-dotenv` and `Path`.

#### [NEW] [hashing.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/utils/hashing.py)
- SHA-256 calculation helpers and Merkle hash utilities for content addressing and verification.

#### [NEW] [logging.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/utils/logging.py)
- Standardized rich-compatible logger configuration.

---

### 2. Core Engine & Data Structures (`src/core/`)

#### [NEW] [memory_node.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/core/memory_node.py)
- Immutable `MemoryNode` dataclass with content hashing (SHA-256), Merkle root calculation over causal parents, serialization (`to_dict` / `from_dict`), and verification (`verify()`).
- Fields: `id`, `timestamp`, `content`, `summary`, `title`, `type` (`decision`, `command`, `hack`, `architecture`, `error`, `context`), `tags`, `scope`, `impact`, `parents`, `children`, `related`, `author`, `model_version`, `status`, `content_hash`, `merkle_root`, `metadata`.

#### [NEW] [memory_dag.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/core/memory_dag.py)
- `MemoryDAG` implementation managing acyclic dependency graphs between memory nodes.
- Cycle detection (`_would_create_cycle`), ancestor/descendant traversal (`get_ancestors`, `get_descendants`), timeline index, type index, tag index, and whole-DAG integrity verification.

#### [NEW] [merkle_tree.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/core/merkle_tree.py)
- Merkle tree calculations for verifiable append-only log state and history consistency.

#### [NEW] [storage.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/core/storage.py)
- SQLite storage backend with thread safety (`threading.Lock`), schema creation, indexes, SQLite FTS5 integration (`memories_fts`), pagination, and export helpers.

---

### 3. Search Engine (`src/search/`)

#### [NEW] [full_text.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/search/full_text.py)
- FTS5 query builder and search handler with query sanitization and ranking.

#### [NEW] [temporal.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/search/temporal.py)
- Time-based slicing, relative time filters (e.g. `session`, `last-24h`, `week`, `month`), and timeline sequencing.

#### [NEW] [bloom_filter.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/search/bloom_filter.py)
- In-memory Bloom filter for ultra-fast existence checks on memory identifiers and tags.

---

### 4. Export & Live Preview Server (`src/export/`)

#### [NEW] [templates.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/export/templates.py)
- Templates for individual memory documents, index summaries, and web preview styling.

#### [NEW] [markdown_exporter.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/export/markdown_exporter.py)
- Markdown file generator organizing exported memories into categorized directories (`decisions/`, `commands/`, `hacks/`, `architecture/`, `errors/`, `context/`) alongside a master `README.md` / `INDEX.md`.

#### [NEW] [preview_server.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/export/preview_server.py)
- Dual-stack HTTP and WebSocket server with real-time reload on storage changes, full search sidebar, interactive type filtering, and clean markdown rendering via Marked.js.

---

### 5. Model Context Protocol (MCP) Integration (`src/mcp/`)

#### [NEW] [tools.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/mcp/tools.py) & [handlers.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/mcp/handlers.py)
- Tool definitions and logic for:
  - `memory_add`: Insert immutable memory entry with type, tags, impact, and relations.
  - `memory_search`: Full-text & type-filtered memory retrieval.
  - `memory_get`: Retrieve complete memory node by ID.
  - `memory_recent`: Query memories within specified days.
  - `memory_context`: Generate condensed project context grouped by type for agent bootstrapping.

#### [NEW] [server.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/mcp/server.py)
- MCP server initialization with support for standard stdio and SSE transport execution.

---

### 6. Command-Line Interface (`src/cli/`)

#### [NEW] [main.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/src/cli/main.py)
- Complete CLI using `typer` and `rich`:
  - `init`: Initialize `.project-memory/` directory and SQLite schema.
  - `remember`: Add memories directly from the terminal.
  - `search`: Search and render rich tables in terminal.
  - `export`: Export memories to markdown directory with optional `--preview`.
  - `serve`: Run live preview server on configurable port.
  - `mcp`: Run MCP server for AI coding agent integration.

---

### 7. Documentation, Templates & Project Files

#### [NEW] [templates/](file:///D:/2026-2027-AI-startup-ideas/project-memory/templates/)
- `memory_template.md`, `index_template.md`, `search_template.html`.

#### [NEW] [docs/](file:///D:/2026-2027-AI-startup-ideas/project-memory/docs/)
- `API.md`, `MCP_TOOLS.md`, `EXAMPLES.md`.

#### [NEW] [requirements.txt](file:///D:/2026-2027-AI-startup-ideas/project-memory/requirements.txt), [setup.py](file:///D:/2026-2027-AI-startup-ideas/project-memory/setup.py), [README.md](file:///D:/2026-2027-AI-startup-ideas/project-memory/README.md), [.env.example](file:///D:/2026-2027-AI-startup-ideas/project-memory/.env.example)

---

### 8. Comprehensive Test Suite (`tests/`)

#### [NEW] [tests/](file:///D:/2026-2027-AI-startup-ideas/project-memory/tests/)
- `test_memory_node.py`: Integrity hash checks, Merkle calculation, serialization.
- `test_memory_dag.py`: Node insertion, cycle prevention, ancestor/descendant traversal.
- `test_storage.py`: SQLite initialization, FTS5 searching, persistence and concurrency.
- `test_search.py`: Full-text queries, temporal range queries, bloom filter checks.
- `test_export.py`: Markdown generation and export directory validation.

---

## Verification Plan

### Automated Tests
Run pytest across all modules:
```powershell
pytest tests/ -v
```

### Manual Verification
1. **CLI Commands**:
   - `python -m src.cli.main init`
   - `python -m src.cli.main remember "Test decision" --type decision --tags "auth,security" --impact high`
   - `python -m src.cli.main search "Test decision"`
   - `python -m src.cli.main export --output ./memory-export`
2. **MCP Verification**:
   - Verify tool schemas and handlers return structured responses properly.
3. **Live Preview Verification**:
   - Test web preview rendering and WebSocket update propagation.
