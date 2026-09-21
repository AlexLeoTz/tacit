"""Canonical agent-rule text written into every initialized workspace.

Kept out of the CLI module so that tests can assert its taxonomy claims stay
in sync with ``Config.MEMORY_TYPES``.
"""

AGENT_RULE_CONTENT = """# Autonomous Institutional Memory Rules (Tacit)

You are connected to Tacit to preserve engineering decisions across chat resets.

## What Tacit Stores vs What NOT to Store:
* **Record Every Completed Task (Distilled)**: Every task that changes the codebase MUST end with a Tacit write — see the Mandatory Task Completion Protocol below. Capture design choices, undocumented workarounds (hacks), environment dependencies, operational commands, and resolved error caveats.
* **NEVER Store Chat History, Logs, or Code Snippets**: Do not pollute the memory database with conversation transcripts, raw terminal logs, or full source code files/snippets. Tacit is an institutional decision ledger, not a code repository or log sink.

## Writing Titles (they are the search index):
* **Every entry MUST have a `title`, and it must be specific.** Only the **title, tags and summary** are embedded into the vector index — the full `content` is not. A vague title therefore makes a memory effectively unfindable by semantic search, no matter how good the content is.
* **Write the title as a self-contained phrase that names the subject**, not a label or a category echo:
  * GOOD: `Replaced Redis sessions with signed JWT cookies`
  * GOOD: `[WinError 32] blocks pip from replacing a running tacit.exe`
  * BAD: `auth fix`, `update`, `decision`, `Error: session issue`
* **Assume the title is read alone**, months later, with no surrounding context and no access to the content. If it would not tell a future agent what to search for, rewrite it.
* **Include the distinguishing detail** — the technology, the component, the error code, the constraint. `Connection pool exhaustion under concurrent writes` beats `Database issue`.
* **Summaries are equally load-bearing**: the `summary` is embedded too, so make it a complete one-sentence statement of the finding, not a teaser.
* **Tags are embedded as well**: 2-5 specific keywords increase both keyword and conceptual recall.

## The Tacit Taxonomy (closed set):
`type` MUST be exactly one of the twelve categories below. The set is closed: never invent a new category, and never use a synonym for one that exists. Pick the category by the question the entry answers, not by the size of the change.

| Category | Answers the question | Use for |
|---|---|---|
| `decision` | "Why this and not the alternative?" | Library/API/algorithm/schema/config choices; refactors; performance strategy |
| `architecture` | "How is the system shaped?" | Components, module boundaries, data flow, contracts between internal parts |
| `error` | "What broke and how was it fixed?" | Diagnosed failures with a root cause and a resolution |
| `hack` | "What are we working around?" | Deliberate workarounds for upstream bugs, library limits, environment barriers |
| `command` | "How do we operate it?" | Operational invocations: migrations, reindexing, recovery, deploy steps |
| `context` | "What is true about our world?" | Descriptive environment, domain, or business background; not a decision |
| `constraint` | "What are we not allowed to do?" | Binding limits: quotas, licences, compliance, platform ceilings, budgets |
| `convention` | "How must code be written here?" | Normative rules: naming, layering, review standards, API shape |
| `security` | "How is it protected?" | Authn/authz model, threat mitigations, secret handling, vuln remediation |
| `performance` | "How fast or expensive is it?" | Measured baselines, bottlenecks, the delta an optimization achieved |
| `integration` | "How does it talk to the outside?" | External service/API/dependency contracts, quirks, pinned versions |
| `migration` | "How does data or versioning move?" | Schema/data/version migrations with rollout and rollback |

Confusable pairs — resolve them this way:
* `decision` vs `architecture`: a `decision` had alternatives; `architecture` describes structure that now exists.
* `context` vs `constraint`: `context` describes, `constraint` forbids. If it can stop a future change, it is a `constraint`.
* `context` vs `convention`: `context` is how things are, `convention` is how they must be.
* `error` vs `hack`: an `error` was fixed; a `hack` is still in place.
* `integration` vs `architecture`: `integration` covers an interface you do not own.

## Rigorous Content Detail Requirements:
* **NEVER write shallow 1-3 line entries in `content`**: The `summary` is a 1-sentence abstract, but `content` MUST be a rich, self-contained Markdown write-up that fully equips future agents without follow-up questions.
* Categories share five content archetypes. Use the archetype for the category you chose:

### Archetype A — Choice / Design (`decision`, `architecture`, `integration`, `migration`)
1. **Context & Problem Statement**: What problem was being solved, and what forced a choice?
2. **Alternatives Evaluated & Rejected**: What else was considered, and specifically why it lost.
3. **Solution & Rationale**: The concrete pattern, data flow, contract, or configuration applied.
4. **Trade-offs & Consequences**: Side effects, performance or maintenance cost, future obligations.
5. **Validation**: How it was verified (tests, benchmarks, manual checks).
   - `migration` must also state **rollout order** and **rollback procedure**.
   - `integration` must also state the **external contract** and any **pinned version**.

### Archetype B — Failure (`error`, `security`)
1. **Symptom / Threat & Trigger**: Exact error text, stack trace, or attack path, plus the conditions that produced it.
2. **Root Cause Analysis**: Why it happened at the code, runtime, dependency, or design level.
3. **Resolution / Mitigation**: The precise change that removed or contained it.
4. **Prevention & Regression Caveats**: Edge cases and anti-patterns to avoid from now on.

### Archetype C — Workaround (`hack`)
1. **Workaround Description**: What the workaround does and where it lives.
2. **Why the Standard Approach Failed**: The upstream bug, limitation, or environment barrier.
3. **Side Effects & Risks**: Performance penalties, correctness limits, or debt introduced.
4. **Decommissioning Criteria**: The concrete condition, release, or milestone that lets it be removed.

### Archetype D — Procedure / Rule (`command`, `convention`)
1. **Exact Specification**: Full CLI invocation with flags and execution context, or the rule stated precisely enough to check mechanically.
2. **Prerequisites & Side Effects**: Migrations, locks, daemon states, or blast radius.
3. **When to Apply vs When NOT to**: Operational guardrails and legitimate exceptions.

### Archetype E — Fact / Limit (`context`, `constraint`, `performance`)
1. **The Fact or Limit**: One unambiguous statement of what is true or binding.
2. **Evidence**: The measurement, source, contract, or document it came from (numbers required for `performance`).
3. **Implications**: What this changes for future design, and what it rules out.

## Multi-Entry Recording (Paired Issues & Decisions):
* When you diagnose an issue and implement a fix or architectural change, you should record **BOTH**:
  1. The `error` node (documenting the failure symptom and root cause).
  2. The `decision` or `hack` node (documenting the architectural fix or workaround).
* **Use `memory_add_batch`** to insert multiple related entries in a single call. You can reference previous items in the batch using `$prev` or `$0` in the `parents` field to link them into the causal graph automatically.

## Preventing Orphan Nodes & Causal Graph Integrity:
* **NEVER Create Orphan Nodes Blindly**: Unless you are creating a completely new, greenfield feature or root architecture, every `decision`, `hack`, `command`, or `error` is derived from, fixes, or relates to an existing component or prior memory.
* **Always Check for Existing Parents First**: Check `memory_context()` or `memory_search()` to identify relevant parent UUIDs before calling `memory_add`.
* **Heed Interactive Warnings**: If `memory_add` responds with a `[TACIT GRAPH NOTICE]` suggesting candidate parents, immediately review them and call `memory_link(child_id=..., parent_id=...)` to preserve graph lineage.

## Mandatory Agent Workflow:
1. **Session Bootstrapping**: At session start or when beginning a new task, call `memory_context()` to load relevance-ranked decisions, active hacks, and solved errors into your context.
2. **Pre-Decision Validation (Check Before Planning)**: Before proposing, planning, or implementing any architectural change, library addition, refactor, or configuration change, you MUST query Tacit (`memory_search` or `memory_context`) to verify whether that decision is allowed, if specific constraints apply, or if that approach was previously tried and invalidated.
3. **Causal Lineage & Taxonomy**: When calling `memory_add` or `memory_add_batch`, always specify:
   - `tags`: At least 2 descriptive keywords (e.g. ['auth', 'jwt', 'security']).
   - `scope`: Affected folder or subsystem (e.g. ['/api/auth']). Ensure paths actually exist in the codebase.
   - `parents`: Link the UUID(s) of any past memories from `memory_context` that this entry modifies, extends, or is derived from.
   - `supersedes`: Link the UUID(s) of any past decisions that this change directly invalidates or replaces.
4. **Mandatory Task Completion Protocol (Document Every Completed Task)**:
   Every task that changes code, configuration, dependencies, or project state MUST end with a Tacit write. Recording is part of finishing the task, not an optional follow-up, and never something you defer to "later" or to the user.
   - **Step 1 — Classify what you just did** using the closed taxonomy above. Pick the category that answers the *knowledge* question, not the size of the diff, and apply the disambiguation rules for the confusable pairs. When two categories both seem to fit, prefer the more specific one (`constraint` over `context`, `integration` over `architecture`, `security` over `decision`).
   - **Step 2 — Document the code, not the conversation**: state what changed in the codebase — the files or directories affected (put them in `scope`), the behaviour before versus after, and the concrete mechanism that produces the new behaviour. Never paste diffs, full file contents, or chat transcripts.
   - **Step 3 — State the verification**: how the change was proven to work (tests added, commands run, manual checks performed). An entry with no verification evidence is incomplete.
   - **Step 4 — Link the graph**: pass `parents` for any memory this builds on and `supersedes` for any past memory this invalidates. When one task produces both a diagnosis and a fix, record them together with `memory_add_batch` using `$prev` or `$0`.
   - **Step 5 — Write, then report**: call `memory_add` (or `memory_add_batch`) before you present your final summary, and mention the recorded node ID(s) in that summary. Every entry needs a specific `title` (see Writing Titles above) — it is what makes the memory findable later.
   - **Only these are exempt**: changes with no behavioural effect on the project — pure formatting, comment or typo fixes, and throwaway experiments you reverted. `tags`, `scope`, and `impact` remain mandatory on every entry you do write.
   - **When in doubt, write it**: a slightly redundant memory is cheap; a lost root cause, rejected alternative, or rationale is expensive. If you skip, you must be able to name which exemption above applies.
"""
