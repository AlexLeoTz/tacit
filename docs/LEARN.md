# 🧠 Project Memory Cortex (PMC) — First-Principles Guide

> **Confidential Internal Engineering & Distribution Blueprint**  
> *Author: Alex Leo*

---

## 1. Why PMC Exists (The Problem of AI Amnesia)

When software engineers work with AI coding agents (Cursor, Claude, Antigravity, OpenCode):
1. **Context Window Compaction**: As conversations exceed token limits, old messages are summarized or discarded. The agent forgets *why* a specific architectural decision was made 20 turns ago.
2. **Session Resets**: Starting a new chat wipes all context.
3. **Repeated Mistakes & Bug Regressions**: Agents re-introduce the same bugs or undo undocumented workarounds ("hacks") previously resolved by another session or teammate.

**Project Memory Cortex (PMC)** solves this by acting as an **immutable, content-addressed institutional memory layer** for your codebase.

---

## 2. Cryptographic Architecture (Why Hashes & Merkle Trees?)

### Why Hashes?
Instead of arbitrary sequential IDs (`1, 2, 3`), every memory node has a **SHA-256 Content Hash** computed from:
$$\text{Content Hash} = \text{SHA-256}(\text{title} + \text{summary} + \text{content} + \text{author} + \text{timestamp})$$

- **Immutability**: If anyone edits a single character of an old decision, its hash changes immediately.
- **Merge Integrity**: Distributed developers working on separate Git branches will never produce ID collisions.

### How the Merkle Root Works:
Every decision is causally linked to its parent decisions:
$$\text{Merkle Root} = \text{SHA-256}(\text{Node Content Hash} + \text{Parent Merkle Roots})$$

```
          [ Merkle Root: 99ee41... ]  <── Single fingerprint of entire history
                     │
          Hash( Hash_C + Merkle_Root_B )
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
    [ Node C Hash ]      [ Merkle Root B ]
  (Celery Command)               │
                    Hash( Hash_B + Hash_A )
                                 │
                     ┌───────────┴───────────┐
                     ▼                       ▼
               [ Node B Hash ]         [ Node A Hash ]
               (EAT Webhook Hack)    (Integer Cents Schema)
```

**The Power of Merkle Roots**:
1. **Single History Fingerprint**: One 64-character root proves the entire ancestral chain.
2. **Instant Tamper Detection**: Changing a decision from 6 months ago invalidates the Merkle root of every descendant decision that relied on it.
3. **Proof of Lineage**: Node C mathematically proves it was created *after* and *because of* Node B.

---

## 3. Directed Acyclic Graph (DAG) & Causal Querying

Real engineering decisions form a causal graph, not a flat list.

### Graph Rules:
- **Directed**: Edges point strictly from parents (causes) to children (effects).
- **Acyclic**: Cycles are mathematically forbidden (`_would_create_cycle()`). A decision cannot depend on its own future child.

### How PMC Resolves Questions:
When a developer asks: *"Why are we running Celery on payments_queue with gevent?"*
1. **Search**: Matches Node C (`Celery Startup Command`).
2. **DAG Traversal (`get_ancestors`)**:
   - Walks up: `Node C` ➔ `Node B (Webhook Timezone Hotfix)` ➔ `Node A (Integer Cents Decision)`.
3. **AI Synthesizes Complete Context**: Explains the background, the bug that triggered it, and the architecture rule, with zero guesswork.

---

## 4. Search Engine: SQLite FTS5 + BM25

Instead of requiring cloud vector databases or expensive embedding API calls on every keystroke:
1. **FTS5 Index**: Fast full-text indexing with BM25 relevance scoring.
2. **Prefix & Token Matching**: Searches multi-word queries (e.g. `"splash screen"`) using tokenized prefix queries (`"splash"* OR "screen"*`) combined with keyword ranking.
3. **Multi-Column Matching**: Matches across title, summary, content, and tags in < 2 milliseconds.

---

## 5. Storage Pipeline: SQLite + Auto Dual-Write

- **`memory.db`**: Primary fast database for sub-millisecond AI agent queries.
- **Categorized Markdown Files**: Automatically writes individual `.md` files to `.project-memory/<category>/` upon memory creation (can be toggled via `PMC_DUAL_WRITE=false`).
- **`pmc export`**: Standalone command to bundle all memories into a clean, standalone documentation website/archive with a master `INDEX.md`.

---

## 6. Global Distribution & Monetization (Zero Followers Playbook)

### You Do Not Need Celebrity Status:
Open-source developers judge tools purely on **utility, speed, and clean documentation**.

### Distribution Steps:
1. **Submit to MCP Directories**:
   - `mcp.so`
   - `glama.ai/mcp/servers`
   - `awesome-mcp-servers` on GitHub
2. **Authentic Community Sharing**:
   - Post on `r/Cursor`, `r/ClaudeAI`, and `r/LocalLLaMA`: *"I built a local MCP server that gives AI coding agents persistent institutional memory across chat resets."*
   - Hacker News (*Show HN: Project Memory Cortex*).

### Monetization Strategy (Open-Core):
- **Free Core (MIT)**: Single-developer local CLI (`pmc`), local SQLite, Merkle DAG, and web preview dashboard.
- **PMC Teams ($15/seat/month)**: Real-time cloud/P2P Merkle DAG sync across all engineers in a team.
- **PMC CI/CD Drift Guard ($49/repo/month)**: GitHub Action bot that blocks pull requests that violate past architectural decisions.
- **Enterprise Compliance Vault**: Tamper-proof decision audit trails for fintech and healthcare enterprises.

---

## 7. Advanced DAG & Agent Features (Auto-Linking, Visualizers & Self-Reflection)

To make persistent institutional memory frictionless and robust, PMC incorporates automated graph linking, visualization tools, and agent self-reflection loops:

### A. Pre-Flight Semantic Auto-Linking
When agents record new decisions, they sometimes omit parent identifiers (`parents`) due to missing context or simple oversight. To resolve this, PMC performs a **pre-flight semantic auto-linking check** on `memory_add`:
- **Heuristic Search**: If no parents are provided, PMC uses the memory's `title`, `summary`, or the start of the `content` to run a search for relevant past entries.
- **Auto-Association**: If a highly relevant historical entry is found, it is automatically assigned as the parent node, preserving the lineage/causal path without manual intervention.

### B. ASCII DAG & Lineage Visualizers
Developers can trace their project's causal history directly inside CLI environments or during agent reasoning processes:
1. **Interactive tree view (`pmc tree`)**: Renders the complete project memory DAG as a color-coded nested ASCII tree.
2. **Visual Ancestry/Descendant Trace (`pmc lineage <node_id>`)**: Displays a localized causal panel outlining the specific "Foundations" (Ancestors) and "Derived Decisions" (Descendants) surrounding a targeted node.
3. **Agent Integration (`memory_get`)**: When agents inspect a memory using the `memory_get` tool, PMC builds the DAG dynamically and appends an ASCII representation of its direct causal lineage so the agent understands the exact decision context.

### C. Upgraded Autonomous Self-Reflection Protocol
PMC instructs AI coding agents to actively participate in maintaining memory hygiene:
- **Mandatory End-of-Task Checkpoint**: After completing any non-trivial coding task, agents are prompted via rules to ask themselves: *"Did I make a non-obvious design choice, apply an undocumented workaround, solve a tricky error, or execute a vital deployment command?"*
- If **yes**, they record it as a structured memory (`memory_add`). If **no**, they refrain from polluting the DAG with redundant logs.
- This self-reflection protocol is embedded directly in generated agent rules (`.agents/rules/project_memory.md`) and the MCP instructions block returned by the server.
