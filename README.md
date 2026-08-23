<div align="center">
  <img src="logo.jpg" alt="Tacit Logo" width="120" />
  <h1>Tacit</h1>
  <p><strong>The Institutional Memory Layer & Decision Lineage Engine for AI Coding Agents</strong></p>
  <p>
    <a href="#why-tacit-the-magic-in-a-nutshell">Why Tacit?</a> •
    <a href="#1-quick-start--installation">Quick Start</a> •
    <a href="#2-ai-agent-integration-mcp-setup">MCP Setup</a> •
    <a href="#3-agent-master-prompt--rules-automated">Master Rules</a> •
    <a href="#4-cli-usage--commands">CLI Commands</a> •
    <a href="#6-mcp-tools-reference">MCP Tools</a> •
    <a href="#license">License</a>
  </p>
</div>

---

## Why Tacit? (The Magic in a Nutshell)

### The New Hire Analogy

Imagine a brilliant senior engineer joins your team on Day 1. 

You wouldn't hand them a 10,000-line dump of raw Slack chats, nor would you expect them to decipher your entire Git commit history before writing their first function. 

And you certainly wouldn't give them a notebook full of contradictory notes where:
* **Page 12 says:** *"We authenticate users with passwords."*
* **Page 40 says:** *"Switched to fingerprint authentication."*
* **Page 88 says:** *"Fingerprint scanners kept failing in production — switched back to passwords."*

A new person skimming that notebook sees three statements that all sound equally true. **Which one do they follow?**

What that senior engineer actually needs is a **crisp, 2-minute morning briefing**:
1. **The 3–5 foundational architectural decisions** that define how the system is built today (and *why* those choices were made).
2. **The active undocumented workarounds ("hacks")** currently preventing outages in production so they don't accidentally "refactor" them away.
3. **The vital operational commands and resolved error caveats** to avoid stepping into known traps.

---

### The AI Amnesia Problem

**Every AI coding agent session (Claude Code, Cursor, Antigravity, OpenCode) is a brand-new engineer with total amnesia.**

When you reset a chat or your conversation compresses past the context window:
1. **Loss of the "Why"**: The agent forgets why an unusual pattern exists and "cleans it up", instantly re-introducing solved bugs and breaking production.
2. **The Flat Memory Trap**: Most vector/agent-memory tools dump flat snippets of *"what"*. When decisions change over time, flat stores feed obsolete, contradictory advice straight into new sessions as active truth.
3. **Repetitive Groundhog Day**: You find yourself re-explaining the same architectural rules, deploy commands, and environment caveats at the start of every session.

---

### How Tacit Works: The 4 Pillars

Tacit acts as an **immutable, content-addressed institutional memory layer with causal supersedence and relevance-ranked bootstrapping**:

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
 │ Hybrid Search │        │  Causal DAG   │        │ Markdown &    │
 │ (BM25 + ONNX) │        │ Lineage Engine│        │ Preview Server│
 └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
         │                        │                        │
         ▼                        ▼                        ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │              Local Project Directory (.tacit/)                   │
 │              - memory.db (SQLite with Relational Edges)          │
 │              - Merkle Hash Tree & Causal Ancestry DAG            │
 └──────────────────────────────────────────────────────────────────┘
```

#### 1. The Causal DAG & The "REPLACED" Sticker System
Engineering history is immutable — you should never silently erase what you did in the past. But when a decision changes, Tacit slaps a typed **`supersedes`** sticker on the old entry pointing to the new one, explaining exactly *why* it was replaced. 
* Dead advice is automatically filtered out of new agent sessions.
* If an agent inspects an old decision, Tacit flashes a warning banner: `⚠️ SUPERSEDED by <successor_id>: "<reason>"`.
* The complete causal ancestry (`derives_from` and `supersedes`) remains intact.

#### 2. The 2-Minute Intelligent Bootstrap Briefing
When an agent starts a session, calling `memory_context()` runs Tacit's multi-signal relevance scoring algorithm:
$$	ext{Score}(d) = 0.35 \cdot 	ext{Impact}(d) + 0.40 \cdot 	ext{Centrality}(d) + 0.25 \cdot 	ext{Recency}(d) - 	ext{Penalty}(d)$$
* **DAG Centrality**: Measures how many later active decisions depend on this node ($f_{	ext{centrality}} = rac{n}{n + 8}$). Foundational choices outrank minor recent tweaks.
* **Recency Half-Life Decay**: A gentle 6-month freshness curve ($f_{	ext{recency}} = 0.5^{(	ext{age\_days} / 180)}$).
* **Neighbor Penalty**: If a related decision was recently superseded, the node receives a decaying deduction.
* **Token-Budgeted Diversity**: Assembles the top context into **Tier 1 (deep reading with lineage)** and **Tier 2 (one-liner summaries by tag)** within a customizable token budget (default: 2,000 tokens / `TACIT_TOKEN_BUDGET`).

#### 3. Local Hybrid Search (FastEmbed ONNX + BM25)
Zero cloud API keys, zero PyTorch bloat (~50MB ONNX runtime). Combines exact lexical matching (SQLite FTS5 / BM25) with dense semantic embeddings (`BAAI/bge-small-en-v1.5`) using **Reciprocal Rank Fusion (RRF)**:
$$	ext{RRF}(d) = \sum_{r \in 	ext{channels}} rac{1}{60 + 	ext{rank}_r(d)}$$
Queries execute in **< 5 milliseconds** on your local CPU with automatic scope and recency boosting.

#### 4. Cryptographic Proofs & Dual-Write Storage
* Every memory is addressed by its **SHA-256 content hash** and linked via a **Merkle root**. `tacit verify` cryptographically proves history has not been tampered with.
* **Dual-Write**: Saves to `memory.db` for fast agent queries AND simultaneously maintains human-readable `.md` files in `.tacit/<category>/`.

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
9. [License](#license)

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

# Or customize token budget directly
tacit briefing --budget 1500
```

### Search Memories (Hybrid BM25 + ONNX Embeddings)
```bash
# Hybrid semantic search with RRF fusion (default)
tacit search "database connection exhaustion"

# Keyword-only search
tacit search "docker" --mode keyword --type command

# Search with active file scope boosting
tacit search "authentication" --scope src/api/auth.py

# Include historical / superseded memories
tacit search "JWT" --include-superseded
```

### Backfill Vector Embeddings
```bash
# Embed all memories in the database using local fastembed (idempotent and resumable)
tacit reindex
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

### Configuration Options & Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TACIT_TOKEN_BUDGET` | `2000` | Token budget cap for `memory_context()` and `tacit briefing`. |
| `TACIT_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX embedding model. |
| `TACIT_DUAL_WRITE` | `true` | Auto-sync `.md` files into `.tacit/<category>/`. Set `false` for SQLite-only. |
| `PREVIEW_PORT` | `4000` | HTTP port for the web dashboard. |
| `PREVIEW_WS_PORT` | `4001` | WebSocket port for live updates. |

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
| `memory_search` | High-speed Hybrid search (BM25 + fastembed ONNX dense vectors via RRF). | `query`, `type`, `tags`, `limit`, `mode`, `scope_hint`, `include_superseded`, `debug` |
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

This project is licensed under the **Functional Source License, Version 1.1, MIT Conversion** ([`FSL-1.1-MIT`](./LICENSE)).

### Plain English Summary:
* **Free for Developers & Organizations**: You are free to use Tacit, modify it, integrate it into your internal workflows, deploy it in proprietary products, and redistribute it without paying any fees.
* **The Only Restriction**: For a period of **two years** from each release date, you cannot take Tacit and offer it as a competing commercial cloud service or managed SaaS platform.
* **Automatic Conversion to MIT**: Exactly two years after each release, the license for that version automatically and permanently converts to the standard, unrestricted **MIT License**.

See the full [`LICENSE`](./LICENSE) file for complete legal terms.
