<div align="center">
  <img src="logo.jpg" alt="Tacit Logo" width="120" />
  <h1>Tacit</h1>
  <p><strong>The Institutional Memory Layer & Decision Lineage Engine for AI Coding Agents</strong></p>
  <p>
    <a href="#1-quick-start--installation">Quick Start</a> •
    <a href="#2-ai-agent-integration-mcp-setup">MCP Setup</a> •
    <a href="#3-agent-master-prompt--rules-automated">Master Rules</a> •
    <a href="#4-cli-usage--commands">CLI Commands</a> •
    <a href="#6-mcp-tools-reference">MCP Tools</a> •
    <a href="#docs">Documentation</a>
  </p>
</div>

---

## Why Tacit?

AI coding assistants (Claude Code, Cursor, Antigravity, OpenCode) suffer from **context compaction and session amnesia**:
- When chats reset or contexts compress, the model loses the **"why"** behind architectural choices.
- Undocumented workarounds (*"hacks"*) get silently reverted, causing bug regressions.
- Decisions get updated or reversed over time, and flat memory stores poison agent context with obsolete contradictory advice.

**Tacit** gives AI coding assistants an **immutable, content-addressed institutional memory layer with causal supersedence and relevance-ranked bootstrapping**:

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                     AI Coding Agent                              │
 │            (Claude Code / Cursor / Antigravity)                  │
 └───────────────────────────────┬──────────────────────────────────┘
                                 │
                   Model Context Protocol (MCP)
                                 │
 ┌───────────────────────────────┴──────────────────────────────────┐
 │                     Tacit Local Engine                           │
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
 │              Local Project Directory (.tacit/)                   │
 │              - memory.db (WAL SQLite with Typed Edges)           │
 │              - Merkle Hash Tree & Causal Ancestry DAG            │
 └──────────────────────────────────────────────────────────────────┘
```

---

## Table of Contents
1. [Quick Start & Installation](#1-quick-start--installation)
2. [AI Agent Integration (MCP Setup)](#2-ai-agent-integration-mcp-setup)
3. [Agent Master Prompt & Rules](#3-agent-master-prompt--rules-automated)
4. [CLI Usage & Commands](#4-cli-usage--commands)
5. [Live Markdown Preview Server & Dashboard](#5-live-markdown-preview-server--dashboard)
6. [MCP Tools Reference](#6-mcp-tools-reference)
7. [Multi-Project Support](#7-multi-project-support)
8. [Testing](#8-testing)

---

## 1. Quick Start & Installation

To get Tacit running in your environment, execute the following commands in sequence:

### Step 1: Install Tacit from source
```bash
# Clone the repository
git clone https://github.com/AlexLeoTz/tacit.git
cd tacit

# Install globally on your machine (editable mode for active development)
pip install -e .
```

> [!IMPORTANT]
> **Windows Installation/Update Note**: Before running `pip install -e .` or `tacit update` on Windows, make sure all running Tacit instances (such as Cursor, Claude Desktop, or `tacit serve`) are stopped. Windows locks active `.exe` binaries, which will cause the installer to crash with a `PermissionError`.

---

### Step 2: Register MCP server globally
This registration command modifies your editor's settings globally. It can be run from any folder or terminal directory:
```bash
# For Antigravity CLI
tacit install-mcp --client antigravity

# For Claude Desktop
tacit install-mcp --client claude

# For Claude Code (Terminal CLI)
tacit install-mcp --client claude-code

# For Cursor
tacit install-mcp --client cursor
```

---

### Step 3: Initialize the project memory directory
Navigate to your specific project workspace directory (e.g. `cd /path/to/my-project`) and initialize the database. **This command must be run inside your project root directory**:
```bash
tacit init
```

---

### Step 4: Run the live markdown preview server
Start the web dashboard to search, view, and insert project memories directly. **This command must be run inside your project root directory**:
```bash
tacit serve
```

---

## 2. AI Agent Integration (MCP Setup)

Tacit runs as a local MCP server that automatically detects whichever project directory your coding harness has open.

---

### Manual MCP Configuration & Client Setup

Tacit runs locally as an **STDIO MCP server**: a local background process communicated with via standard input/output streams by your AI coding client.

> [!NOTE]
> **Harness Compatibility**: Tacit is thoroughly tested and verified to work natively in **Antigravity CLI**, **Claude Desktop**, **Claude Code**, and **Cursor**.

#### 1. Claude Code & Claude Desktop
Add this to your `claude_desktop_config.json` (on Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tacit": {
      "command": "tacit",
      "args": ["mcp"]
    }
  }
}
```

#### 2. Cursor
Go to **Settings** -> **Features** -> **MCP**, click **+ Add New MCP Server**, and configure:
* **Name**: `tacit`
* **Type**: `stdio`
* **Command**: `tacit mcp`

---

## 3. Agent Master Prompt & Rules (Automated)

**You do not need to manually create rule files.**

When you run `tacit init` in any project, it **automatically generates** the rule files for you:
* **Antigravity / AGY CLI**: `.agents/rules/tacit.md`
* **Cursor**: `.cursorrules`
* **MCP Prompts**: Exposed directly over the MCP protocol as `tacit-instructions`.

If you ever need to inspect or customize the rules, here is the generated template:

```markdown
# Autonomous Institutional Memory Rules (Tacit)

You are connected to Tacit to preserve engineering decisions across chat resets.

## Critical Concept (What to Store vs What NOT to Store):
* **ONLY Store Distilled Tacit Knowledge**: Record non-obvious design choices, undocumented workarounds (hacks), specific environment dependencies, critical operational commands, and resolved error caveats.
* **NEVER Store Raw Code or Chat Transcripts**: Do not pollute the memory database with raw source code files, copy-pasted logs, or complete conversation histories. Keep entries high-density and concise.

## Mandatory Agent Workflow:
1. **Session Bootstrapping**: At session start or when beginning a new task, call `memory_context()` to load relevance-ranked decisions, active hacks, and solved errors into your context.
2. **Causal Lineage & Taxonomy**: When calling `memory_add`, always specify:
   - `tags`: At least 2 descriptive keywords (e.g. ['auth', 'jwt', 'security']).
   - `scope`: Affected folder or subsystem (e.g. ['/api/auth']). Ensure paths actually exist in the codebase.
   - `parents`: Link the UUID(s) of any past memories from `memory_context` that this entry modifies, extends, or is derived from.
   - `supersedes`: Link the UUID(s) of any past decisions that this change directly invalidates or replaces.
3. **End-of-Task Checkpoint (Autonomous Self-Reflection)**:
   - At the conclusion of any non-trivial coding task, ask yourself:
     "Did I make a non-obvious design choice, apply an undocumented workaround, solve a tricky error, or execute a vital deployment command?"
   - If YES, record it using `memory_add` (`decision`, `architecture`, `hack`, `command`, or `error`). If invalidating a past decision, specify `supersedes=[<id>]`.
   - If NO (e.g., routine refactor or typo fix), do not pollute project memory.
```

---

## 4. CLI Usage & Commands

You can run `tacit` in **any** project directory on your machine. It automatically discovers and initializes the `.tacit/` directory for that workspace.

### Initialize a Project
```bash
# Run in the root of your project
tacit init
```

### View Relevance-Ranked Session Briefing
```bash
# Generates intelligent DAG-centrality and recency-decayed project briefing
tacit briefing

# Or with custom token budget
tacit briefing --budget 1500
```

### Record a Memory
```bash
# Add a decision
tacit remember "Migrated authentication from sessions to JWT with 15-minute rotation" \
  --type decision \
  --tags "auth,security,jwt" \
  --impact high

# Add a decision that supersedes a previous one
tacit remember "Reverted to sessions due to JWT refresh rotation vulnerabilities" \
  --type decision \
  --tags "auth,security,session" \
  --impact high \
  --supersedes 4a9f1234 \
  --relation-note "JWT token leakage risk in distributed workers"

# Add a critical command
tacit remember "docker compose -f docker-compose.prod.yml up -d --build" \
  --type command \
  --tags "deploy,docker,prod"

# Add a workaround / hack (attaching parent nodes to establish causal lineage)
tacit remember "Temporary fix for SQLite thread lock: set WAL mode and 5s timeout" \
  --type hack \
  --tags "sqlite,db,bugfix" \
  --parents 54bd72c1
```

### Search Memories
```bash
# Full-text search with BM25 ranking
tacit search "JWT"

# Filter by type
tacit search "docker" --type command
```

### Verify Cryptographic Integrity
```bash
# Recomputes and checks SHA-256 hashes and Merkle lineage across all nodes
tacit verify
```

### Lifecycle Management (Supersede & Retract)
```bash
# Explicitly supersede a memory node with a successor
tacit supersede <old_node_id> --by <new_node_id> --reason "Revised architecture"

# Retract an erroneously recorded entry
tacit retract <node_id> --reason "Never deployed"
```

### View Recent Memories
```bash
# Show memories recorded in the last 7 days
tacit recent --days 7

# Show last 20 memories of type 'error'
tacit recent --days 30 --type error --limit 20
```

### Export Standalone Markdown Documentation
```bash
# Export all memories to categorized markdown files with an INDEX.md table of contents
tacit export

# Export to a custom backup folder
tacit export --output ./docs/project-memories
```

### Dual-Write & Configuration Options

By default, Tacit uses **Dual-Write mode**: it saves memories to `memory.db` (for SQLite FTS5 search) AND simultaneously creates human-readable `.md` files in `.tacit/<category>/`.

To disable markdown auto-sync and use SQLite-only mode:

```bash
# In your terminal or .env file:
TACIT_DUAL_WRITE=false
```

### Update Tacit Globally & Refresh Workspace
```bash
# Run in your project directory to upgrade Tacit globally and refresh local agent rules
tacit update
```

### View Details & Delete

```bash
# View full markdown of a specific memory (accepts UUID or prefix)
tacit get 4a9f

# Delete a specific memory (auto-removes corresponding .md file)
tacit delete 4a9f

# Clear all memories for the current project
tacit clear
```

### Visualizing Causal DAGs & Lineage

```bash
# Renders the entire project decision DAG as a nested ASCII tree
tacit tree

# Traces causal foundations (ancestors) and derived decisions (descendants) for a specific node
tacit lineage 4a9f
```

---

## 5. Live Markdown Preview Server & Dashboard

Tacit includes a real-time web dashboard with live WebSocket reload, theme switcher (Light, Dark, System), full-text search, type filtering, and markdown rendering.

```bash
# 1. Start live preview server (defaults to HTTP: 4000, WebSocket: 4001 or next available)
tacit serve

# 2. Specify custom ports for both HTTP and WebSocket
tacit serve --port 3000 --ws-port 3001
```

---

## 6. MCP Tools Reference

When connected via MCP, AI agents have access to the following 6 tools:

| Tool | Purpose | Key Arguments |
|---|---|---|
| `memory_add` | Persist a new immutable decision, command, hack, architecture, or error. Supports superseding past decisions. | `content`, `type`, `summary`, `tags`, `impact`, `parents`, `supersedes`, `relation_note` |
| `memory_search` | High-speed FTS5 full-text search. | `query`, `type`, `tags`, `limit` |
| `memory_get` | Fetch the full markdown content & Merkle lineage by ID. Displays alert banners if superseded/retracted. | `node_id` |
| `memory_recent` | List chronological memories from the last N days. | `days`, `limit`, `type` |
| `memory_context` | Generate an intelligent relevance-ranked, token-budgeted project briefing (DAG centrality + impact + recency decay). | `budget`, `scope_hint`, `timeframe` |
| `memory_projects`| List all registered project workspaces across your machine. | None |

> **Safety Notice**: Deletion is intentionally restricted to human developers via the CLI (`tacit delete <id>`) or Dashboard UI to prevent AI agents from accidentally erasing historical institutional memory.

---

## 7. Multi-Project Support

Tacit automatically keeps each codebase's memories isolated:
- Every project stores its database at `<project-root>/.tacit/memory.db`.
- Auto-detects the project root from `.git`, `package.json`, `pyproject.toml`, or `.tacit`.
- Track all projects on your machine with:
  ```bash
  tacit projects
  ```

---

## 8. Testing

Run the full test suite using `pytest`:

```bash
pytest tests/ -v
```

---

## License

MIT License.
