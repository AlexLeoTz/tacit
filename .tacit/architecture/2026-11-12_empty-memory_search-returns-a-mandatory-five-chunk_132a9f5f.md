# Empty memory_search returns a mandatory five-chunk memory_chronicle sweep

**ID**: `132a9f5f-ec45-49c0-9586-3551479c4f41`  
**Type**: `architecture`  
**Date**: 2026-11-12 13:06:48 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
A no-result search now returns the store total and executable 20% chunk offsets; memory_chronicle gained offset paging so five sub-agents can scan every node before the agent concludes the memory is absent.

## Content
### Context & Problem Statement
Hybrid search ranks titles, summaries, tags and vectors; it cannot prove absence. A false negative causes the worst class of agent failure: silently re-proposing a design the project already rejected, or re-debugging an error whose root cause is recorded under different wording. The requirement is that an agent always gets a path to the answer.

### Alternatives Evaluated & Rejected
1. **Return a better 'not found' message only.** Rejected: a message is not executable and agents paraphrase it away.
2. **Automatically dump the whole store into the tool result.** Rejected: blows the context window and defeats the point of a search tool.
3. **Require one agent to read everything serially.** Rejected: slow and still context-bound; parallel sub-agents with disjoint slices cover the store.

### Solution & Rationale
When `memory_search` yields zero rows, `MemoryMCPHandlers._exhaustive_fallback` builds a protocol from `storage.get_count()`:

- `agents = min(5, total)`, `chunk = ceil(total / agents)`;
- each sub-agent receives `memory_chronicle(limit=chunk, offset=i*chunk, brief=false, content_chars=0, include_superseded=true, include_retracted=true, project=<root>)`;
- Step 1 is always a retry without `scope_hint` plus a literal `memory_grep`;
- the response also carries machine-readable `total_memories`, `fallback.chunks` and `diagnostics` (vector used/failed, stale embedding count), so a non-LLM caller can drive the same sweep.

`memory_chronicle` now supports `offset` end-to-end: `MemoryStorage.get_chronological(offset=...)`, `count_chronological`, `ChronicleEngine.build(offset=...)`, the MCP schema/handler and `tacit chronicle --offset`. Scoped reads filter before slicing so an offset never counts rows the scope would drop; entry indices stay absolute (`[003]`, `[004]`). Responses report `total`, `offset` and `truncated`, and an offset past the end is explained.

The same rule was written into `src/core/agent_rules.py`, the MCP `tacit-instructions` prompt and every tool description, because tool descriptions are what the model actually reads.

### Trade-offs & Consequences
An empty search can now trigger five sub-agent calls, which is deliberately expensive. The cost is justified only for genuine misses; a non-empty result never triggers the sweep. Very large stores may need a chunk split again into 20% sub-chunks, which the protocol instructs.

### Validation
`tests/test_search_fallback.py` checks the 5-chunk partition of 23 memories (`[0,5,10,15,20]` limits `[5,5,5,5,3]`), that the chunks cover all 23 IDs exactly once, the scoped retry instruction, the empty-store answer, and the vector-unavailable note. `test_chronicle.py` covers offset paging, absolute indices and offset-past-end. Full suite: 385 passed.

## Taxonomy & Relations
- **Tags**: search, fallback, chronicle, agents, recall
- **Scope**: src/mcp/handlers.py, src/core/chronicle.py, src/mcp/server.py, src/mcp/tools.py, src/core/agent_rules.py, tests/test_search_fallback.py, tests/test_chronicle.py
- **Parents**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`, `80f0cdb1-ef24-4a1f-94e2-0795999f768c`
- **Children**: None
- **Related**: None

---
*Content Hash*: `ea3bf932a5a3a05416d985dc5e38583a21232084ebf78787fe0c57500bc98af7`  
*Merkle Root*: `bd5c19c46e9d0651d8b77e628ec2692b523f083f4cab545c8b548e12367077ea`
