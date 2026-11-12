# Tacit store is kept tracked by git via a managed gitignore block and one-time staging

**ID**: `80f0cdb1-ef24-4a1f-94e2-0795999f768c`  
**Type**: `decision`  
**Date**: 2026-11-12 13:06:48 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
tacit init and MCP startup re-include .tacit in .gitignore, stage the store once, and skip projects that the enclosing repo deliberately ignores, so a clone cannot silently lose every memory.

## Content
### Context & Problem Statement
A Tacit store is institutional memory, not a build artifact. When `.tacit` was covered by a template `.gitignore` (dot-directory rules, `*.db`, or a hand-written `.tacit/`), cloning the repository on another machine produced healthy code and zero memories. The failure is silent until an agent is asked why something was built a certain way.

### Alternatives Evaluated & Rejected
1. **Only document 'commit .tacit' in the README.** Rejected: documentation does not override an existing ignore rule, and the failure is invisible.
2. **Only `git add -f .tacit`.** Rejected: force-adding works once but future Markdown memory files stay ignored, and it would also force-add the model cache.
3. **Rewrite the user's whole `.gitignore`.** Rejected: destroys unrelated rules and is hostile.

### Solution & Rationale
`src/utils/git_tracking.py::ensure_store_tracked` runs from `tacit init` and `tacit mcp` startup:

1. Resolve the enclosing work tree with `git rev-parse --show-toplevel` (no-op outside git).
2. If the project directory itself is ignored by the enclosing repo, leave that repo untouched — this protects test scratch dirs, vendored trees and generated workspaces inside a larger checkout.
3. Append a marker-delimited block to the top-level `.gitignore`, re-including each ancestor and `store/**`, then re-ignoring the regenerable cache (`models/`, `_*/`), SQLite WAL/SHM/journal, `*.pyc` and `__pycache__/`. The block is replaced, never duplicated, so `tacit move` refreshes it.
4. Stage the store once with `git add -A`; if a later nested ignore rule still wins, force-add only the known data files (`memory.db`, `*.md`, config/map JSON, `location`) — never the cache.
5. Stage the `.gitignore` change only when it is what un-ignored the store. Tacit never commits.

Paths are gitignore-escaped (`*?[]`, leading `!`/`#`) so directories such as `project[1]` still work.

### Trade-offs & Consequences
- The SQLite database is binary and can conflict across branches; the Markdown dual-write remains the human-readable record. Users can still choose not to commit, but they must actively opt out.
- Auto-staging is limited to the store and the fix that makes it visible; unrelated work is untouched.
- Projects that are not yet git repositories get a clear message and are fixed on the next `tacit init`/MCP start after `git init`.

### Validation
`tests/test_git_tracking.py` covers an ignored store, WAL/cache exclusions, idempotence, already-tracked stores, relocated nested stores, escaped block content, non-repos and an ignored project inside an enclosing repo. An end-to-end `tacit init` in a temporary git repo showed `memory.db` and `.gitignore` staged and `git check-ignore .tacit/memory.db` returning no match.

## Taxonomy & Relations
- **Tags**: git, gitignore, data-loss, init, durability
- **Scope**: src/utils/git_tracking.py, src/cli/main.py, tests/test_git_tracking.py, tests/test_mcp_and_cli.py
- **Parents**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`
- **Children**: None
- **Related**: None

---
*Content Hash*: `61432af3e64a251162a7a77a2627909a5841d933e830ee44d6d761965e9fe567`  
*Merkle Root*: `d4e599d6b9c0add65164b717573a07834b5cba3200be3af259ec0291697db0df`
