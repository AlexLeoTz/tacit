# Project Memory Cortex (PMC)

> **Persistent, immutable, timestamped institutional memory for AI coding agents.**  
> Survives context window wipes, model switches, compaction, and chat resets.

---

## Motivation and The Problem It Solves

### The Problem: AI Amnesia in Modern Software Engineering
Large Language Models (LLMs) and coding agents (Claude, Cursor, Antigravity, OpenCode) possess reasoning capabilities, but suffer from **project amnesia**:
1. **Context Window Limits & Compaction Loss**: As conversations grow, context is summarized or wiped. The agent forgets why a specific architectural decision was made 20 turns ago.
2. **Session Resets & Model Switching**: Starting a new chat or switching between models (e.g. Gemini, Claude 3.7, GPT-4o) destroys working institutional memory.
3. **Repeated Mistakes & Bug Regressions**: Agents often re-introduce the same bugs, test the same failed hypotheses, or undo undocumented workarounds ("hacks") previously resolved by another session or teammate.
4. **Scattered Tacit Knowledge**: Critical deployment commands, environment quirks, and architectural caveats live only in chat histories rather than in an indexed, verifiable repository.

### What is Project Memory Cortex?
**Project Memory Cortex** is a content-addressed, cryptographic **institutional memory layer** for AI software engineers. It runs locally as a Model Context Protocol (MCP) server and embeds into your existing developer workflow:
- **Immutable Knowledge DAG**: Every architectural decision, setup command, hack, error fix, and design constraint is stored with a cryptographic SHA-256 hash and Merkle root.
- **Fast Full-Text Retrieval (FTS5 + BM25)**: Agents instantly recall relevant decisions using natural language search.
- **Bootstrapping on Session Start**: Agents automatically query past context on session startup (`memory_context`) to immediately align with historical design decisions.
- **Human-in-the-Loop Dashboard**: Developers get a live-reloading visual web interface to explore, filter, audit, and clean project knowledge.

---

## Architecture Overview

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                     AI Coding Agents & Editors                   │
 │       (Antigravity, Cursor, Claude Desktop, OpenCode, VSCode)     │
 └───────────────────────────────┬──────────────────────────────────┘
                                 │ Standard MCP Protocol (stdio / SSE)
                                 ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                   FastMCP Server Layer (FastMCP)                 │
 │   Tools: memory_add, memory_search, memory_get, memory_context   │
 └───────────────────────────────┬──────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
 ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
 │ SQLite + FTS5 │        │  Merkle DAG   │        │ Markdown &    │
 │ Engine (BM25) │        │ Lineage Engine│        │ Preview Server│
 └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
         │                        │                        │
         ▼                        ▼                        ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │              Local Project Directory (.project-memory/)          │
 │              - memory.db (Encrypted / WAL SQLite)                │
 │              - Merkle Hash Tree & Causal Ancestry DAG            │
 └──────────────────────────────────────────────────────────────────┘
```

---

## Table of Contents
1. [Installation](#1-installation)
2. [AI Agent Integration (MCP Setup)](#2-ai-agent-integration-mcp-setup)
3. [Agent Master Prompt & Rules](#3-agent-master-prompt--rules-automated)
4. [CLI Usage & Commands](#4-cli-usage--commands)
5. [Live Markdown Preview Server](#5-live-markdown-preview-server)
6. [MCP Tools Reference](#6-mcp-tools-reference)
7. [Multi-Project Support](#7-multi-project-support)
8. [Testing](#8-testing)

---

## 1. Installation

Install the package globally in your Python environment:

```bash
# Clone the repository
git clone https://github.com/AlexLeoTz/project-memory-cortext.git
cd project-memory-cortext

# Install globally on your machine (editable mode for active development)
pip install -e .
```

After installation, the **`pmc`** and **`project-memory`** CLI commands will be available globally in any terminal and in any project directory on your computer.

---

## 2. AI Agent Integration (MCP Setup)

Project Memory Cortex runs as a local MCP server that automatically detects whichever project directory your AI editor has open.

### A. One-Click Automatic Setup

Run the built-in installer for your favorite AI editor:

```bash
# 1. Antigravity & Antigravity CLI (writes to ~/.gemini/config/mcp_config.json)
pmc install-mcp --client antigravity

# 2. Claude Desktop (writes to claude_desktop_config.json)
pmc install-mcp --client claude

# 3. Cursor (writes to Cursor global storage config)
pmc install-mcp --client cursor

# 4. View JSON snippet without writing
pmc install-mcp --client print
```

---

### B. Manual MCP Configuration

If you prefer to configure manually, add the following entry to your AI client's MCP configuration:

#### 1. **Antigravity / Antigravity CLI (`~/.gemini/config/mcp_config.json`)**:
```json
{
  "mcpServers": {
    "project-memory": {
      "command": "pmc",
      "args": ["mcp"]
    }
  }
}
```

#### 2. **Claude Desktop (`claude_desktop_config.json`)**:
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "pmc",
      "args": ["mcp"]
    }
  }
}
```

#### 3. **Cursor (`cursor_desktop_config.json` or Settings > Features > MCP)**:
* **Command**: `pmc`
* **Args**: `mcp`

---

## 3. Agent Master Prompt & Rules (Automated)

**You do not need to manually create rule files.**

When you run `pmc init` in any project, it **automatically generates** the rule files for you:
* **Antigravity / AGY CLI**: `.agents/rules/project_memory.md`
* **Cursor**: `.cursorrules`
* **MCP Prompts**: Exposed directly over the MCP protocol as `project-memory-instructions`.

If you ever need to inspect or customize the rules, here is the generated template:

```markdown
# Autonomous Institutional Memory Rules (PMC)

You are connected to Project Memory Cortex to preserve engineering decisions across chat resets.

## Mandatory Agent Workflow:
1. **Session Bootstrapping**: At session start or when beginning a new task, call `memory_context(timeframe="week")` to load existing decisions, active hacks, and solved errors into your context.
2. **Causal Lineage & Taxonomy**: When calling `memory_add`, always specify:
   - `tags`: At least 2 descriptive keywords (e.g. ['auth', 'jwt', 'security']).
   - `scope`: Affected folder or subsystem (e.g. ['/api/auth']).
   - `parents`: Link the UUID(s) of any past memories from `memory_context` that this entry modifies, extends, or is derived from.
3. **End-of-Task Checkpoint (Autonomous Self-Reflection)**:
   - At the conclusion of any non-trivial coding task, ask yourself:
     "Did I make a non-obvious design choice, apply an undocumented workaround, solve a tricky error, or execute a vital deployment command?"
   - If YES, record it using `memory_add` (`decision`, `architecture`, `hack`, `command`, or `error`).
   - If NO (e.g., routine refactor or typo fix), do not pollute project memory.
```

---

## 4. CLI Usage & Commands

You can run `pmc` in **any** project directory on your machine. It automatically discovers and initializes the `.project-memory/` directory for that workspace.

### Initialize a Project
```bash
# Run in the root of your project
pmc init
```

### Record a Memory
```bash
# Add a decision
pmc remember "Migrated authentication from sessions to JWT with 15-minute rotation" \
  --type decision \
  --tags "auth,security,jwt" \
  --impact high

# Add a critical command
pmc remember "docker compose -f docker-compose.prod.yml up -d --build" \
  --type command \
  --tags "deploy,docker,prod"

# Add a workaround / hack
pmc remember "Temporary fix for SQLite thread lock: set WAL mode and 5s timeout" \
  --type hack \
  --tags "sqlite,db,bugfix"
```

### Search Memories
```bash
# Full-text search with BM25 ranking
pmc search "JWT"

# Filter by type
pmc search "docker" --type command
```

### View Recent Memories
```bash
# Show memories recorded in the last 7 days
pmc recent --days 7

# Show last 20 memories of type 'error'
pmc recent --days 30 --type error --limit 20
```

### Export Standalone Markdown Documentation
```bash
# Export all memories to categorized markdown files with an INDEX.md table of contents
pmc export

# Export to a custom backup folder
pmc export --output ./docs/project-memories
```

### Dual-Write & Configuration Options

By default, PMC uses **Dual-Write mode**: it saves memories to `memory.db` (for SQLite FTS5 search) AND simultaneously creates human-readable `.md` files in `.project-memory/<category>/`.

To disable markdown auto-sync and use SQLite-only mode:

```bash
# In your terminal or .env file:
PMC_DUAL_WRITE=false
```

### Update PMC Globally & Refresh Workspace
```bash
# Run in your project directory to upgrade PMC globally and refresh local agent rules
pmc update
```

### View Details & Delete

```bash
# View full markdown of a specific memory (accepts UUID or prefix)
pmc get 4a9f

# Delete a specific memory (auto-removes corresponding .md file)
pmc delete 4a9f

# Clear all memories for the current project
pmc clear
```

### Visualizing Causal DAGs & Lineage

PMC provides built-in tools to inspect project history and dependencies:

```bash
# Renders the entire project decision DAG as a nested ASCII tree
pmc tree

# Traces causal foundations (ancestors) and derived decisions (descendants) for a specific node
pmc lineage 4a9f
```

### Pre-Flight Semantic Auto-Linking

When recording a memory (`pmc remember` or `memory_add`), PMC checks for parent relationships. If no parent links are supplied, the core runs a **pre-flight semantic similarity lookup** on existing memories. If a highly relevant context node is found, it automatically links it as a parent node, ensuring DAG continuity without manual intervention.

---

## 5. Live Markdown Preview Server & Dashboard

PMC includes a real-time web dashboard with live WebSocket reload, theme switcher (Light, Dark, System), full-text search, type filtering, and markdown rendering.

```bash
# 1. Start live preview server (defaults to HTTP: 4000, WebSocket: 4001 or next available)
pmc serve

# 2. Specify custom ports for both HTTP and WebSocket
pmc serve --port 3000 --ws-port 3001

# 3. Export to Markdown files and launch live preview immediately with custom ports
pmc export --preview --port 3000 --ws-port 3001
```

> **Automatic Port Conflict Resolution**: If a port is already taken, PMC automatically scans and binds to the next available free port without crashing.

Open your browser at `http://localhost:4000` (or your configured port) to interact with your project memories visually.

---

## 6. MCP Tools Reference

When connected via MCP, AI agents have access to the following 6 tools:

| Tool | Purpose | Key Arguments |
|---|---|---|
| `memory_add` | Persist a new immutable decision, command, hack, architecture, or error. | `content`, `type`, `summary`, `tags`, `impact`, `parents` |
| `memory_search` | High-speed FTS5 full-text search. | `query`, `type`, `tags`, `limit` |
| `memory_get` | Fetch the full markdown content & Merkle lineage by ID. | `node_id` |
| `memory_recent` | List chronological memories from the last N days. | `days`, `limit`, `type` |
| `memory_context` | Bootstrap an AI agent session with organized project knowledge. | `timeframe` (`session`, `week`, `month`, `all`) |
| `memory_projects`| List all registered project workspaces across your machine. | None |

> **Safety Notice**: Deletion is intentionally restricted to human developers via the CLI (`pmc delete <id>`) or Dashboard UI to prevent AI agents from accidentally erasing historical institutional memory.

---

## 7. Multi-Project Support

Project Memory Cortex automatically keeps each codebase's memories isolated:
- Every project stores its database at `<project-root>/.project-memory/memory.db`.
- Auto-detects the project root from `.git`, `package.json`, `pyproject.toml`, or `.project-memory`.
- Track all projects on your machine with:
  ```bash
  pmc projects
  ```

---

## 8. Testing

Run the full test suite using `pytest`:

```bash
pytest tests/ -v
```

---

## License

MIT License. Designed for AI agents and human developers.


