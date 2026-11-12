<div align="center">
  <img src="logo.jpg" alt="Tacit Logo" width="120" />
  <h1>Tacit</h1>
  <p><strong>Institutional memory and decision lineage for AI coding agents</strong></p>
  <p>
    <a href="#quick-start">Quick Start</a> •
    <a href="#what-your-agent-gets">What your agent gets</a> •
    <a href="#commands">Commands</a> •
    <a href="#reference">Reference</a> •
    <a href="#license">License</a>
  </p>
</div>

---

Every new chat starts from zero. The model can write code, but it does not know the workaround you added for a library quirk, the deploy command that actually works, or why last month's approach was abandoned. So you re-explain it — and if you forget, the agent "cleans up" your workaround and the bug comes back.

**Tacit is a local memory layer that fixes this.** It stores distilled engineering knowledge — decisions, hacks, constraints, commands, resolved errors — in your repo, and hands it back to the agent at the start of every session. The memory itself is a SQLite store inside your project; embeddings use the Gemini API, so an internet connection and a `GEMINI_API_KEY` are needed for semantic search (keyword search works without one).

```bash
pip install -e .                 # from a clone
export GEMINI_API_KEY="..."     # https://aistudio.google.com/apikey
tacit install-mcp --client claude-code   # or cursor / antigravity / deepseek-harness
cd /path/to/your/project && tacit init
```

That's it. From then on your agent briefs itself before it starts work, and records what it learned when it finishes.

---

## What your agent gets

**A briefing, not a dump.** `memory_context()` returns a token-budgeted set of memories ranked by *PageRank authority* over the decision graph — how many later decisions trace back to it. Foundational choices outrank fresh notes, and the graph is computed over the whole project, so a recent window never flattens the ranking.

**History on demand.** `memory_chronicle` returns *every* memory oldest-first — including the decisions that were later replaced — for questions like "why is it built this way?" or "have we tried this before?".

**A map of the codebase.** `project_structure` returns the captured layout — directories, file names, line counts, and a one-line description of what each file contains — so a new session knows where things are without opening twenty files.

**Scope that actually filters.** Tell it you are working in `backend/app` and you get `backend/app` memories. Not "mostly", not "boosted": other subsystems are excluded, and project-wide knowledge is always included. Memories from another repository cannot appear at all.

**Search that respects the graph.** Hybrid BM25 + Gemini embeddings fused by RRF, then weighted by authority. Titles, tags and summaries are embedded — never full content — which is why the agent rules insist on specific titles. An empty search is treated as a signal to scan the whole store in chunks, never as proof that the memory does not exist.

**Memories that travel with the code.** `tacit init` (and every MCP startup) makes sure git does not ignore `.tacit`: it appends a managed `.gitignore` block and stages the store once. Clone the repository on another machine and the decisions are there — only the regenerable embedding cache stays untracked.

---

## Quick Start

**1. Install**

```bash
git clone https://github.com/AlexLeoTz/tacit.git
cd tacit
pip install -e .

# Semantic search uses Google Gemini embeddings
export GEMINI_API_KEY="..."   # https://aistudio.google.com/apikey
```

> Updating later: `tacit update` detects an editable checkout and updates it in place (`git pull` + `pip install -e .`). Confirm with `tacit --version`, which prints the version *and* the directory the running code came from.

**2. Register the MCP server with your editor**

```bash
tacit install-mcp --client antigravity   # or: claude-code | claude | cursor | deepseek-harness
```

<details>
<summary>Manual configuration</summary>

Add to your client's MCP config (`claude_desktop_config.json` on Windows lives at `%APPDATA%\Claude\`):

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

For Cursor: **Settings → Features → MCP → + Add New MCP Server**, type `stdio`, command `tacit mcp`.
</details>

**3. Initialize your project**

```bash
cd /path/to/my-project
tacit init
```

This creates `.tacit/` (database + config), writes agent rules into `.agents/rules/tacit.md` and `.cursorrules`, asks whether to keep a project-structure snapshot, and verifies that `.tacit` is tracked by git. If a template `.gitignore` ignores dot-directories or `*.db`, Tacit adds a managed block that re-includes the store while keeping its embedding cache and SQLite WAL files out. Commit `.tacit` with your code so a fresh clone keeps every memory.

If `GEMINI_API_KEY` is not set, initialization still succeeds, but search is keyword-only until you set the key and run `tacit reindex`.

**4. Optional: the dashboard**

```bash
tacit serve      # http://localhost:4000 — search, browse and write memories
```

---

## Commands

The handful you will actually type:

| Command | What it does |
|---|---|
| `tacit briefing` | Ranked, budgeted session briefing (`--scope backend/app` to narrow it) |
| `tacit chronicle` | Every memory oldest-first — `--brief` for a one-line timeline |
| `tacit remember "..."` | Record a decision, hack, command or error |
| `tacit search "query"` | Hybrid BM25 + semantic search |
| `tacit grep pgvector` | Literal match over titles and summaries (no model needed) |
| `tacit get <uuid>` | Print one memory verbatim (`--raw` for plain Markdown) |
| `tacit structure` | The captured codebase map (`--refresh` to re-walk it) |
| `tacit files` | The per-file table: `--pending`, `--set`, `--refresh`, `--stats` |
| `tacit serve` | Local dashboard and Markdown preview |
| `tacit update` | Update Tacit itself |
| `tacit --help` | Everything else: `tree`, `lineage`, `export`, `verify`, `move`, `projects`, `supersede`, `retract`, `reindex`, `delete`, `clear`, `mcp` |

---

## For agents

`tacit init` writes rules your agent reads automatically, so the loop works without you prompting it:

1. **Start**: brief on the project, then read the structure map, then fill any missing file-table rows.
2. **Before deciding**: check whether the decision is already made, constrained, or was already tried and rejected.
3. **Finish**: record what changed and how it was verified, link it to the decisions it derives from, and refresh the file rows touched.

Tacit stores distilled knowledge only — never chat logs, terminal output or source files.

---

# Reference

The deep end. Skip it unless you are changing Tacit or debugging it.

## MCP tools

| Tool | Purpose | Key arguments |
|---|---|---|
| `memory_add` | Record one immutable memory. `scope` is mandatory in practice — it is the filter every later read applies. | `content`, `type`, `title`, `summary`, `tags`, `scope`, `impact`, `parents`, `supersedes`, `project` |
| `memory_add_batch` | Record several related memories atomically (`$prev` links them). | `entries`, `project` |
| `memory_search` | Hybrid BM25 + Gemini-embedding search, scope-filtered, ranked relevance × authority. An empty result returns a mandatory five-chunk sweep protocol. | `query`, `type`, `tags`, `limit`, `mode`, `scope_hint`, `project` |
| `memory_context` | The briefing. | `budget`, `timeframe`, `scope_hint`, `project` |
| `memory_chronicle` | Full history, oldest first, superseded included; `offset` pages it in chunks. | `brief`, `limit` (0 = all), `offset`, `type`, `timeframe`, `scope_hint`, `project` |
| `memory_get` | One memory by exact UUID, with lineage banners. | `node_id`, `project` |
| `memory_grep` | Literal substring match over titles and summaries. | `keyword`, `type`, `limit`, `scope_hint`, `project` |
| `memory_recent` | Chronological recent memories. | `days`, `limit`, `scope_hint`, `project` |
| `memory_link` | Attach an edge (`derives_from`, `supersedes`, `related`). | `child_id`, `parent_id`, `relation`, `reason` |
| `memory_pin` | Pin memories so they always appear in the briefing. | `ids`, `unpin`, `project` |
| `project_structure` | The workspace map: names, nesting, line counts, descriptions. | `refresh`, `path`, `include_gists`, `max_lines`, `project` |
| `project_files_pending` | Files whose table row is missing or stale, with facts precomputed. | `limit`, `project` |
| `project_files_update` | Write many file rows in one call (records author + timestamp). | `entries`, `by`, `project` |
| `project_gist` | Describe a single file. | `path`, `gist`, `author`, `project` |
| `memory_projects` | Every workspace registered on this machine. | — |

Plus one prompt, `tacit-instructions`, carrying the same rules the CLI writes into your repo.

### Scope is a filter, and `project` selects the workspace

* **`scope_hint` filters.** Only memories recorded against those paths — plus project-wide memories — are returned. Omitting it reads the whole workspace. An empty answer names the scope that emptied it, so a wrong scope is never mistaken for missing knowledge.
* **`project` names the workspace.** One Tacit MCP server can serve several workspaces; pass your workspace root on every call. Without it, the call falls back to the directory the server was launched in.
* **Tacit never invents a store.** If the launch directory is a container (home, drive root, system or temp folder) or has no project marker (`.tacit`, `.git`, `pyproject.toml`, `package.json`), `tacit mcp` refuses to create a store there and reports it rather than letting one store answer for every workspace underneath.

### When search comes back empty, scan — do not conclude

`memory_search` ranks titles, summaries, tags and vectors; it cannot prove that a memory is absent. A miss can mean different wording, a superseded node, or content that was never embedded. So an empty result is not a shrug: it returns the store's total size and an executable protocol.

The agent must:

1. retry once without `scope_hint`, and try `memory_grep` on the literal symbol or error code;
2. split the **entire** store into five chunks of ~20% (`limit = ceil(total / 5)`) and spawn five sub-agents;
3. give sub-agent *i* `memory_chronicle(limit=<chunk>, offset=<i * chunk>, brief=false, content_chars=0, include_superseded=true, include_retracted=true, project=<root>)`;
4. merge the five reports, citing UUIDs and verbatim evidence; only then may it say no memory exists.

This is deliberately expensive. The alternative failure — silently re-proposing an approach the project already rejected — is far more expensive.

## How ranking works

Briefing score, per memory:

$$\text{Score} = \text{Authority} \times (0.6 + 0.4 \cdot \text{Impact}) \times (0.7 + 0.3 \cdot \text{Recency}) \times (1 + \text{type prior}) - \text{penalty}$$

* **Authority** is PageRank over `child → derives_from → parent` links. A memory many later memories build on outranks a fresh one nobody referenced.
* **Impact and recency are bounded tie-breakers**: together they can reorder comparable memories, never overturn a decisive authority gap.
* **Penalty** pushes down a memory adjacent to a recently corrected one, fading over ~2 months.
* **Search** is `RRF × recency × (0.5 + 0.5 · authority)`; relevance and authority multiply, so neither can rescue the other.

Token budget comes from `TACIT_TOKEN_BUDGET` (default 2000): the top slice is rendered in full with lineage, the remainder as one-liners grouped by tag.

## Memory model

* **Immutable nodes.** A change of mind is a *new* node with a `supersedes` edge, never an edit. Superseded guidance is filtered out of briefings but stays inspectable, with a warning banner when read directly.
* **Closed taxonomy.** `decision`, `command`, `hack`, `architecture`, `error`, `context`, `constraint`, `convention`, `security`, `performance`, `integration`, `migration`.
* **Integrity.** Every node carries a SHA-256 `content_hash` and a Merkle root over its ancestry; `tacit verify` recomputes both.
* **Dual-write.** Memories live in `memory.db` *and* as human-readable Markdown under `.tacit/<category>/` (`TACIT_DUAL_WRITE=false` for SQLite only).
* **Auto-linking.** A candidate parent at affinity ≥ 0.50 is attached silently; 0.15–0.50 emits a `[TACIT GRAPH NOTICE]` listing candidates for the agent to link.

## Multi-project and the file table

* Every project keeps its own database at `<project-root>/.tacit/memory.db`; the root is discovered from `.tacit`, `.git`, `pyproject.toml` or `package.json`.
* **The store is tracked.** `tacit init` and MCP startup append a managed `.gitignore` block that re-includes `.tacit`, and stage the store the first time. Commit it with the code; without it, a clone starts from zero memories. The embedding cache and SQLite WAL files remain ignored.
* A workspace root may hold several repositories (`backend/` + `frontend/`): they are discovered by looking for `.git`, or pinned with `tacit structure --set-repos backend,frontend`.
* Container directories — and directories with no project marker at all — are never treated as a project root, so unrelated workspaces cannot end up sharing one store. `tacit init` is the one command that may create a project in a plain directory.
* `tacit projects` lists every workspace registered on the machine.
* `tacit move <subfolder>` relocates a store (database, exports and Markdown together) and leaves a pointer at `<root>/.tacit/location`, so nothing else changes. Run `tacit init` again (or restart `tacit mcp`) to rewrite the managed gitignore block for the new path.

**The file table.** `tacit init` can keep a structure snapshot of the workspace: directory and file **names only, never source code**, plus one row of metadata per file — lines of code, size, language, content hash, a compact description, and who last updated it and when. Agents read it with `project_structure`, fill missing rows with `project_files_pending` + `project_files_update`, and refresh rows after editing a file; a row whose hash no longer matches the file is reported as stale. Dependency trees, build output and caches are skipped; dotfiles such as `.env` are kept, because they are part of the layout.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | **Recommended.** Google Gemini embeddings (`gemini-embedding-001`, 768-dim). Without it, search is keyword-only. |
| `OPENAI_API_KEY` | — | Optional alternative: `text-embedding-3-small` (1536-dim). Gemini wins when both keys are set unless `TACIT_EMBED_PROVIDER=openai`. |
| `TACIT_EMBED_PROVIDER` | auto | Force `gemini` or `openai` when both keys are present. |
| `TACIT_GEMINI_MODEL` | `gemini-embedding-001` | Gemini embedding model override. |
| `TACIT_GEMINI_DIM` | `768` for `gemini-embedding-*` | Output dimensionality (128–3072). Changing it requires `tacit reindex --force`. |
| `TACIT_OPENAI_EMBED_MODEL` | `text-embedding-3-small` | OpenAI model override. |
| `TACIT_EMBED_BATCH_SIZE` | `20` | Items per remote embedding request. |
| `TACIT_EMBED_MIN_INTERVAL` | `2.0` | Minimum seconds between remote embedding requests. |
| `TACIT_VECTOR_MIN_SIMILARITY` | `0.30` | Minimum cosine similarity for a vector hit. |
| `TACIT_TOKEN_BUDGET` | `2000` | Briefing token budget. |
| `TACIT_PROJECT` | CWD | Pin the workspace, overriding directory discovery. |
| `TACIT_HOME` | `~/.gemini/config` | Where the cross-project registry and update cache/log live. Set it to keep that state elsewhere (portable installs, tests, containers). |
| `TACIT_DUAL_WRITE` | `true` | Write Markdown beside the database. |
| `TACIT_NO_PATH_VALIDATION` | — | Set `true` to skip validating that `scope` paths exist. |
| `PREVIEW_PORT` / `PREVIEW_WS_PORT` | `4000` / `4001` | Dashboard ports. |

## Updating Tacit

If Tacit was installed editable, `tacit update` runs `git pull` + `pip install -e .` in place instead of installing from the Git URL. `tacit --version` prints the version and the directory the code came from — if that path is not the checkout you are editing, reinstall from the right one.

**Windows.** A running `tacit.exe` (including the MCP server your editor started) cannot be replaced in place — hence `[WinError 32] ... tacit.exe -> tacit.exe.deleteme`. `tacit update` handles this: it runs detached, waits for the current process to exit, stops leftover `tacit serve`/`tacit mcp` daemons and their backing `python.exe`, quarantines the old launcher, clears stale `~acit-…dist-info` leftovers, then reinstalls. Because the detached updater has no console, its output goes to `~/.gemini/config/tacit_update.log` and `tacit_update_status.json`; the *next* `tacit` command reports how the run ended. If it keeps failing, quit the editors that have the Tacit MCP server configured and re-run it.

## Testing

```bash
pytest tests/ -v
```

The suite is self-contained: every fixture builds a mock project under `tests/_*/`, and `tests/conftest.py` redirects Tacit's per-machine state (`TACIT_HOME`) into the workspace, so a run never touches your real registry or projects.

---

## License

This project is licensed under the **Functional Source License, Version 1.1, MIT Conversion** ([`FSL-1.1-MIT`](./LICENSE)).

* **Free for developers and organizations**: use it, modify it, integrate it, deploy it, redistribute it.
* **The only restriction**: for two years from each release, third parties cannot offer it as a competing commercial cloud service or managed SaaS platform.
* **Automatic conversion to MIT**: exactly two years after each release, that version's license permanently becomes standard **MIT**.

See [`LICENSE`](./LICENSE) for the complete terms.
