<div align="center">
  <img src="logo.jpg" alt="Tacit Logo" width="120" />
  <h1>Tacit</h1>
  <p><strong>The Institutional Memory Layer and Decision Lineage Engine for AI Coding Agents</strong></p>
  <p>
    <a href="#the-problem-loss-of-context-across-new-chats">The Problem</a> •
    <a href="#how-tacit-works">How Tacit Works</a> •
    <a href="#1-quick-start-and-installation">Quick Start</a> •
    <a href="#2-ai-agent-integration-mcp-setup">MCP Setup</a> •
    <a href="#3-agent-rules-automated">Master Rules</a> •
    <a href="#4-cli-usage-and-commands">CLI Commands</a> •
    <a href="#6-mcp-tools-reference">MCP Tools</a> •
    <a href="#license">License</a>
  </p>
</div>

---

## The Problem: Loss of Context Across New Chats

Every time you start a new chat in **Claude Code, Cursor, Antigravity, or OpenCode**, the AI model starts with a clean slate and no memory of previous sessions.

The model knows how to write clean code, but it lacks the unwritten context of your project:

* It does not know the undocumented workarounds ("hacks") you added to fix environment or library quirks.
* It does not know the specific operational and deployment commands needed to run your services.
* It does not know past architecture decisions or why an earlier approach was changed.

Every time you reset a chat or your conversation exceeds the context window, you have to re-type setup commands, re-explain your services, and re-warn the agent about the same constraints.

If you forget to explain a workaround, the AI model may assume the code looks redundant and refactor it away, which can re-introduce bugs you previously resolved.

---

## How Tacit Works

Tacit provides a local institutional memory layer for AI coding tools. At the start of a task, the agent receives a concise project briefing with active decisions, workarounds, and commands.

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
 │ (BM25 + Dense)│        │ Lineage Engine│        │ Preview Server│
 └───────┬───────┘        └───────┬───────┘        └───────┬───────┘
         │                        │                        │
         ├─ Gemini (Remote API)   │                        │
         ├─ ONNX (Local CPU)      │                        │
         │                        │                        │
         ▼                        ▼                        ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │              Local Project Directory (.tacit/)                   │
 │              - memory.db (SQLite with Relational Edges)          │
 │              - Merkle Hash Tree & Causal Ancestry DAG            │
 └──────────────────────────────────────────────────────────────────┘
```

---

### Core Mechanics

#### 1. Instant Session Bootstrapping (`memory_context()`)
At the start of every session, your AI agent calls `memory_context()` to load an intelligent, token-budgeted project briefing. Memories are ranked by **PageRank authority** over the causal graph — the same backlink intuition that ranks web pages:

$$\text{Authority}(d) = \text{PageRank over } child \rightarrow parent \text{ links} \qquad \text{Score}(d) = \text{Authority}(d) \times \text{Impact}(d) \times \text{Recency}(d) - \text{Penalty}(d)$$

* **Authority leads**: a memory that many later memories trace back to outranks a fresh one nobody built on. A backlink from a foundational decision is worth more than one from a throwaway note.
* **Bounded tie-breakers**: impact and recency are multipliers confined to `[0.6, 1.0]` and `[0.7, 1.0]`, so together they can reorder comparable memories but can never overturn a decisive authority gap.
* **Supersede penalty**: a memory sitting next to a recently corrected one is pushed down, and the deduction fades over ~2 months.
* **Token Budgeting**: Assembles the top context into **Tier 1 (deep reading with lineage)** and **Tier 2 (one-liner summaries by tag)** within your configured token budget (`TACIT_TOKEN_BUDGET`).

Pass `timeframe` (`week`, `30d`, an ISO date, …) to restrict *which* memories may appear. Authority is always computed over the whole active graph — ranking only within a recent window would leave a handful of memories with almost no links between them, where every score is identical.

#### 2. Causal DAG and The "REPLACED" Sticker System
Engineering history is immutable; you should never erase past lessons. When an architectural choice changes, Tacit attaches a typed **`supersedes`** edge to the old entry pointing to the new one, explaining *why* it was replaced. 
* Dead advice is filtered out of active briefings so stale rules never poison fresh prompts.
* If an agent inspects an old decision, Tacit shows a warning banner: `⚠️ SUPERSEDED by <successor_id>: "<reason>"`.
* The complete causal ancestry (`derives_from` and `supersedes`) remains inspectable.

#### 3. Autonomous End-of-Task Reflection
Tacit turns your AI coding tool into an active collaborator in memory hygiene. Every task that changes the codebase ends with a mandatory checkpoint that classifies the knowledge into a closed taxonomy, documents what changed in the code, states how it was verified, and links the causal graph. Only genuinely behaviour-free changes (formatting, comment or typo fixes) are exempt.

#### 4. Hybrid Search Engine (BM25 + Embeddings, ranked by Authority)
Combines exact lexical keyword matching (SQLite FTS5 / BM25) with dense semantic embeddings using **Reciprocal Rank Fusion (RRF)**, then multiplies by the same PageRank authority used for briefings:

$$\text{RRF}(d) = \sum_{r \in \text{channels}} \frac{1}{60 + \text{rank}_r(d)} \qquad \text{Score}(d) = \text{RRF}(d) \times \text{Scope} \times \text{Recency} \times \bigl(0.5 + 0.5 \cdot \text{Authority}(d)\bigr)$$

Relevance says *"about the query"*; authority says *"worth reading"*. Because they multiply, neither can rescue the other — a highly-cited but off-topic memory cannot surface for an unrelated query.

* **Embedding providers are pluggable**: `OPENAI_API_KEY` (`text-embedding-3-small`, 1536-dim) → `GEMINI_API_KEY` (`gemini-embedding-001`, 768-dim) → local fastembed ONNX (`bge-small-en-v1.5`, 384-dim, offline and zero-config).
* **Only titles, tags and summaries are embedded** — never the full content. That makes a write roughly 10× cheaper and produces a sharper vector, but it also means the title is the search index. The agent rules require a specific, self-descriptive title on every entry.
* **Exact symbols, flags, and error codes** are protected by BM25 exact matching.
* **Switching providers requires `tacit reindex --force`**: vectors from different models are not comparable, and Tacit will tell you when stored vectors no longer match the active provider rather than silently returning nothing.

#### 5. Multi-Tier Candidate Auto-Linking & Interactive Orphan Warnings
To prevent isolated orphan nodes and guarantee graph lineage:
* **Multi-Signal Affinity Ranking**: Evaluates Scope Overlap (0.40), Tag Jaccard Similarity (0.30), Keyword Overlap (0.20), Cross-Type Causality (e.g. `error` $\rightarrow$ `decision`, 0.08), and Recency Decay (0.10).
* **Automatic High-Confidence Linking ($\ge 0.50$)**: High-affinity parents are automatically attached and annotated.
* **Interactive Graph Notice ($0.15 \le \text{Score} < 0.50$)**: Emits a `[TACIT GRAPH NOTICE]` in the tool result with ranked candidate parents and ready-to-run `memory_link` commands so the agent can quickly connect relationships.

#### 6. Cryptographic Proofs and Dual-Write Storage
* Every memory is addressed by its **SHA-256 content hash** and linked via a **Merkle root**. `tacit verify` verifies history has not been altered.
* **Dual-Write**: Saves to `memory.db` for fast agent queries and maintains human-readable `.md` files in `.tacit/<category>/`.

---

## Table of Contents
1. [Quick Start and Installation](#1-quick-start-and-installation)
2. [AI Agent Integration (MCP Setup)](#2-ai-agent-integration-mcp-setup)
3. [Agent Rules (Automated)](#3-agent-rules-automated)
4. [CLI Usage and Commands](#4-cli-usage-and-commands)
5. [Live Markdown Preview Server and Dashboard](#5-live-markdown-preview-server-and-dashboard)
6. [MCP Tools Reference](#6-mcp-tools-reference)
7. [Multi-Project Support](#7-multi-project-support)
8. [Testing](#8-testing)
9. [License](#license)

---

## 1. Quick Start and Installation

To get Tacit running in your environment, execute the following commands in sequence:

### Step 1: Install Tacit from source
```bash
# Clone the repository
git clone https://github.com/AlexLeoTz/tacit.git
cd tacit

# Install globally on your machine (editable mode for active development)
pip install -e .
```

> [!TIP]
> **Updating later**: `tacit update` detects an editable (`pip install -e .`) checkout and updates it in place with `git pull` + `pip install -e .`, so the clone you installed from is never replaced by a Git-URL install. Verify the result with `tacit --version`.

---

### Step 2: Register MCP server globally
This registration command modifies your editor configuration globally. It can be run from any folder:
```bash
# For Antigravity IDE & CLI
tacit install-mcp --client antigravity

# For Claude Code (Terminal CLI)
tacit install-mcp --client claude-code

# For Cursor
tacit install-mcp --client cursor

# For Deepseek harness
tacit install-mcp --client deepseek-harness
```

---

### Step 3: Initialize the project memory directory
Navigate to your specific project workspace directory (e.g. `cd /path/to/my-project`) and initialize the database. Run this command inside your project root directory:
```bash
tacit init
```

---

### Step 4: Run the live markdown preview server
Start the web dashboard to search, view, and insert project memories directly. Run this command inside your project root directory:
```bash
tacit serve
```

---

## 2. AI Agent Integration (MCP Setup)

Tacit runs as a local MCP server that automatically detects whichever project directory your coding tool has open.

---

### Manual MCP Configuration and Client Setup

Tacit runs locally as an **STDIO MCP server**: a local background process communicated with via standard input/output streams by your AI coding client.

> [!NOTE]
> **Harness Compatibility**: Tacit is tested and verified to work natively in **Antigravity CLI**, **Claude Desktop**, **Claude Code**, and **Cursor**.

#### 1. Claude Code and Claude Desktop
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

## 3. Agent Rules (Automated)

When you run `tacit init` in any project, it generates rule files automatically:
* **Antigravity / AGY CLI**: `.agents/rules/tacit.md`
* **Cursor**: `.cursorrules`
* **MCP Prompts**: Exposed directly over the MCP protocol as `tacit-instructions`.

### What Tacit Stores vs What It Does NOT Store
* **Tacit Stores**: Distilled tacit knowledge: non-obvious design choices, undocumented workarounds (hacks), specific environment dependencies, critical operational commands, and resolved error caveats.
* **Tacit Does NOT Store**: Raw chat history, full conversation logs, copy-pasted terminal output, or entire source code files/snippets. Tacit is an institutional decision ledger, not a code repository or log sink.

### Agent Workflow Protocols
1. **Bootstrap (`memory_context`)**: Query project context at the start of a session or when working in a new area.
2. **Pre-Decision Validation**: Before proposing, planning, or implementing any architectural change, library addition, or refactor, the agent checks memory to verify if that decision is allowed or if an earlier attempt was already invalidated.
3. **Lineage (`parents` & `supersedes`)**: Link new decisions to parent nodes or indicate when a past decision is being superseded.
4. **Autonomous Self-Reflection**: At the conclusion of non-trivial tasks, record new distilled tacit knowledge.

---

## 4. CLI Usage and Commands

You can run `tacit` in any project directory on your machine. It automatically discovers and initializes the `.tacit/` directory for that workspace.

### Initialize a Project
```bash
# Run in the root of your project
tacit init
```

### View Relevance-Ranked Session Briefing
```bash
# Generates DAG-centrality and recency-decayed project briefing
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

# Include historical or superseded memories
tacit search "JWT" --include-superseded
```

### Backfill Vector Embeddings
```bash
# Embed all memories missing embeddings (idempotent and resumable)
tacit reindex

# Rebuild every vector — required after switching embedding provider
tacit reindex --force
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

# Add a command
tacit remember "docker compose -f docker-compose.prod.yml up -d --build" \
  --type command \
  --tags "deploy,docker,prod"

# Add a workaround / hack with parent links
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

### Lifecycle Management (Supersede and Retract)
```bash
# Mark a memory node as superseded by a successor
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

### Configuration Options and Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TACIT_TOKEN_BUDGET` | `2000` | Token budget cap for `memory_context()` and `tacit briefing`. |
| `TACIT_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX embedding model. |
| `TACIT_DUAL_WRITE` | `true` | Auto-sync `.md` files into `.tacit/<category>/`. Set `false` for SQLite-only. |
### Live Markdown Preview Server & Visual Dashboard
```bash
# Start visual dashboard & live preview server (defaults to http://localhost:4000)
tacit serve
# Or use the dashboard alias:
tacit dashboard

# Start with custom ports or without opening a browser window
tacit serve --port 3000 --ws-port 3001 --no-open
```

### Visualizing Causal DAGs and Lineage
```bash
# Renders the entire project decision DAG as a nested tree
tacit tree

# Traces causal foundations (ancestors) and derived decisions (descendants) for a specific node
tacit lineage 4a9f
```

### Managing Registered Workspaces
```bash
# List all registered and discovered project workspaces on this machine
tacit projects
```

### Deleting or Clearing Memories
```bash
# Delete a specific memory node from SQLite and export directory
tacit delete <node_id>

# Clear all memories from the current project database (requires confirmation)
tacit clear
```

### Updating Tacit Globally
```bash
# Update Tacit to the latest version from GitHub and refresh project rule files
tacit update

# Confirm the installed version (use this instead of guessing)
tacit --version
```

If Tacit was installed from a clone with `pip install -e .`, the update automatically runs `git pull` + `pip install -e .` instead of installing from the Git URL. Force the source path explicitly with `tacit update --source`.

**Windows notes.** A running `tacit.exe` (including an MCP server started by your editor) cannot be replaced in place — that is the source of the `[WinError 32] ... tacit.exe -> tacit.exe.deleteme` error. `tacit update` handles this for you: it runs detached, waits for the current process to exit, stops leftover `tacit serve`/`tacit mcp` daemons *and* their backing `python.exe` processes, quarantines the old launcher, clears stale `~acit-…dist-info` leftovers, and then reinstalls.

Because that updater has no console, its output goes to:

| Path | Contents |
|---|---|
| `~/.gemini/config/tacit_update.log` | Full updater log, including raw `pip` output |
| `~/.gemini/config/tacit_update_status.json` | Machine-readable result of the last run |

Run `tacit update` again to be shown the log path and the failure reason if the previous run did not finish cleanly. If it keeps failing, quit the editors that have the Tacit MCP server configured and re-run it.

**Verify you are updating the checkout you think you are.** `tacit --version` prints both the version and the directory the running code came from:

```
tacit 0.1.0
D:\startups-ideas\tacit\tacit
```

An editable install (`pip install -e .`) stays pinned to the directory it was installed from, so a *different* clone is never the one being executed. If that path is not the checkout you are working in, reinstall from the right one (`cd <checkout> && pip install -e .`); `tacit update` also warns about this when it detects the mismatch.

### Configuration Options and Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | `None` | Google Gemini API key for `gemini-embedding-001` (768-dim) embeddings. Used when `OPENAI_API_KEY` is not set. If neither key is set, Tacit falls back to local fastembed ONNX on CPU. |
| `OPENAI_API_KEY` | `None` | OpenAI API key for `text-embedding-3-small` (1536-dim) embeddings. Highest-priority provider. |
| `TACIT_OPENAI_EMBED_MODEL` | `text-embedding-3-small` | OpenAI embedding model to use. |
| `TACIT_TOKEN_BUDGET` | `2000` | Token budget cap for `memory_context()` and `tacit briefing`. |
| `TACIT_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Local FastEmbed ONNX embedding model (used only when no API key is set). |
| `TACIT_DUAL_WRITE` | `true` | Auto-sync `.md` files into `.tacit/<category>/`. Set `false` for SQLite-only. |
| `PREVIEW_PORT` | `4000` | HTTP port for the web dashboard. |
| `PREVIEW_WS_PORT` | `4001` | WebSocket port for live updates. |

---

## 5. Live Markdown Preview Server and Dashboard

Tacit includes a local interactive web dashboard (`tacit dashboard` / `tacit serve`) with live WebSocket reload, project switcher, search, category filtering, and markdown rendering.

```bash
# 1. Start live preview server and web dashboard (defaults to HTTP: 4000, WebSocket: 4001)
tacit serve
# Or
tacit dashboard

# 2. Specify custom ports for both HTTP and WebSocket
tacit serve --port 3000 --ws-port 3001

# 3. Target a specific project directory
tacit dashboard --project /path/to/another-project
```

> **Smart Instance Detection**: If a Tacit server or dashboard is already running on port 4000, `tacit serve` detects the active instance, opens your browser to the running dashboard, and exits cleanly without spawning duplicate server processes.


---

## 6. MCP Tools Reference

When connected via MCP, AI agents have access to the following 6 tools:

| Tool | Purpose | Key Arguments |
|---|---|---|
| `memory_add` | Persist an immutable decision, command, hack, architecture, or error. Supports auto-linking and orphan warnings. | `content`, `type`, `summary`, `tags`, `impact`, `parents`, `supersedes`, `relation_note` |
| `memory_link` | Explicitly attach or adjust causal edges between nodes (`derives_from`, `supersedes`, `related`). | `child_id`, `parent_id`, `relation`, `reason` |
| `memory_search` | Hybrid search (BM25 + dense vectors via RRF), ranked by relevance × PageRank authority. | `query`, `type`, `tags`, `limit`, `mode`, `scope_hint`, `include_superseded`, `debug` |
| `memory_get` | Fetch markdown content and Merkle lineage by ID. Shows alert banners if superseded or retracted. | `node_id` |
| `memory_recent` | List chronological memories from the last N days. | `days`, `limit`, `type` |
| `memory_context` | Generate a token-budgeted project briefing ranked by PageRank authority (impact and recency as bounded tie-breakers). | `budget`, `scope_hint`, `timeframe` |
| `memory_projects`| List all registered project workspaces across your machine. | None |

> Deletion is restricted to developers via the CLI (`tacit delete <id>`) or Dashboard UI to prevent AI agents from removing historical institutional memory.

---

## 7. Multi-Project Support

Tacit keeps each codebase memories isolated:
- Every project stores its database at `<project-root>/.tacit/memory.db`.
- Auto-detects the project root from `.git`, `package.json`, `pyproject.toml`, or `.tacit`.
- Track all projects on your machine with:
  ```bash
  tacit projects
  ```

---

## 8. Testing

Run the test suite using `pytest`:

```bash
pytest tests/ -v
```

---

## License

This project is licensed under the **Functional Source License, Version 1.1, MIT Conversion** ([`FSL-1.1-MIT`](./LICENSE)).

### Plain English Summary:
* **Free for Developers and Organizations**: You are free to use Tacit, modify it, integrate it into your internal workflows, deploy it in products, and redistribute it without fees.
* **The Only Restriction**: For a period of **two years** from each release date, third parties cannot take Tacit and offer it as a competing commercial cloud service or managed SaaS platform.
* **Automatic Conversion to MIT**: Exactly two years after each release, the license for that version automatically and permanently converts to the standard **MIT License**.

See the [`LICENSE`](./LICENSE) file for complete legal terms.
