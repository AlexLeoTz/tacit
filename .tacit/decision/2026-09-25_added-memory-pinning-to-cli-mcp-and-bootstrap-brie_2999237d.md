# Added Memory Pinning to CLI, MCP, and Bootstrap Briefing

**ID**: `2999237d-a580-47e8-a8a5-3e9b4cefeb76`  
**Type**: `decision`  
**Date**: 2026-09-25 12:03:49 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
Added tacit pin CLI command and memory_pin MCP tool to pin critical institutional knowledge at the end of memory context regardless of score.

## Content
### Context & Problem Statement
Developers and AI agents frequently deal with critical institutional invariants, rules, and core architectural guidelines that must never be missed or truncated during session bootstrap, regardless of the age or PageRank score of the memory. The previous bootstrap algorithm ranked memories strictly based on graph authority, impact, and recency, which meant older but essential invariants could be omitted or demoted to one-liners if newer memories dominated the token budget.

### Alternatives Evaluated & Rejected
1. *Artificially inflating PageRank or impact scores*: Rejected because it would distort graph centrality calculations and could still be superseded or decayed over time.
2. *Hardcoding invariants into prompt templates*: Rejected because project-specific constraints differ per repository and need to be dynamically curatable by developers and agents at runtime.
3. *A dedicated separate tool just for invariants*: Rejected because keeping all institutional knowledge in the unified Tacit store and causal graph allows consistent querying, linking, and management.

### Solution & Rationale
Implemented a dedicated pinning mechanism across Tacit storage, bootstrap engine, MCP server, and CLI:
1. **Database Schema**: Added `pinned_memories (id TEXT PRIMARY KEY, pinned_at REAL NOT NULL, pinned_by TEXT NOT NULL DEFAULT 'dev')` to SQLite storage with methods `pin_memories()`, `unpin_memories()`, `clear_pinned_memories()`, `get_pinned_ids()`, and `get_pinned_memories()`.
2. **Bootstrap Briefing**: `BootstrapEngine.generate_briefing` retrieves pinned memories, isolates them from standard candidate scoring to avoid token budget competition, and appends them under `── Pinned by DEV (important tacit knowledge) ──────────` at the end of the context, rendered in full content (`★ PINNED`).
3. **CLI Interface**: Implemented `tacit pin <id ...>` command with `--unpin`, `--list`, `--clear`, and `--project` flags, complete with table rendering and candidate suggestions for misspelled IDs.
4. **MCP Tool & Handlers**: Added `memory_pin` tool with `ids`, `unpin`, and `project` arguments, plus updated the `tacit-instructions` system prompt.
5. **Agent Rules**: Updated `src/core/agent_rules.py` and `.agents/rules/tacit.md` with explicit instructions for agents to inspect the `Pinned by DEV` section at the end of `memory_context`.

### Trade-offs & Consequences
Pinned memories are rendered in full at the end of the briefing and take priority context space. If many memories are pinned, context length increases; developers should curate pinned memories judiciously.

### Validation
Verified via comprehensive test suite in `tests/test_pin.py` covering storage pin/unpin/clear/cascade delete, bootstrap briefing rendering and ordering, MCP handler execution, MCP tool definition, CLI invocations, and agent rule text. All 7 pinning tests and 22 regression tests passed cleanly.

## Taxonomy & Relations
- **Tags**: pinning, context, cli, mcp, bootstrap
- **Scope**: src/cli, src/core, src/mcp
- **Parents**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`
- **Children**: None
- **Related**: None

---
*Content Hash*: `fbefabcbbc3c16a5da461b92e2b2a1ccc58a52bbfcdb2b4134515e30c9123189`  
*Merkle Root*: `99fb4485315ddd81d308a956119d33b5930b7107b764f9cf69c1a70060153c3a`
