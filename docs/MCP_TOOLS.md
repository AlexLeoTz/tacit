# Model Context Protocol (MCP) Tool Reference

Project Memory Cortex exposes 5 standard MCP tools for AI coding assistants (Claude Desktop, Cursor, Antigravity, OpenCode).

---

## Tool Specifications

### 1. `memory_add`
Persist a new immutable memory node into institutional project memory.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `content` | `string` | **Yes** | Detailed description, command snippet, architecture record, or error details. |
| `type` | `string` | No | One of: `decision`, `command`, `hack`, `architecture`, `error`, `context`. Default: `decision`. |
| `summary` | `string` | No | Short 1-sentence summary (auto-generated if omitted). |
| `title` | `string` | No | Index title. |
| `tags` | `array<string>` | No | List of keyword tags (e.g. `["docker", "cuda", "build"]`). |
| `scope` | `array<string>` | No | File paths or components impacted. |
| `impact` | `string` | No | `high`, `medium`, or `low`. Default: `medium`. |
| `parents` | `array<string>` | No | Array of parent memory IDs this node causally derives from. |
| `related` | `array<string>` | No | Array of related memory IDs. |
| `project` | `string` | No | Target project name or root directory. Defaults to current active workspace. |

---

### 2. `memory_search`
Search all project memories using SQLite FTS5 full-text matching.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | **Yes** | Keyword query string (e.g. `JWT token expiration`). |
| `type` | `string` | No | Optional category filter (`decision`, `hack`, etc.). |
| `tags` | `array<string>` | No | Optional list of tags to filter by. |
| `limit` | `integer` | No | Maximum number of results. Default: 10. |
| `project` | `string` | No | Target project name or root directory. |

---

### 3. `memory_get`
Retrieve the full details and lineage of a specific memory entry.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | **Yes** | Unique UUID of the target memory node. |
| `project` | `string` | No | Target project name or root directory. |

---

### 4. `memory_recent`
Retrieve chronological memories from the last N days.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `days` | `integer` | No | Days to look back. Default: 7. |
| `limit` | `integer` | No | Maximum number of results. Default: 20. |
| `project` | `string` | No | Target project name or root directory. |

---

### 5. `memory_context`
Aggregate institutional memory grouped by categories (`decision`, `architecture`, `hack`, `error`) to bootstrap a new AI agent session.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `timeframe` | `string` | No | Scope: `session`, `week`, `month`, `all`. Default: `week`. |
| `project` | `string` | No | Target project name or root directory. |

---

### 6. `memory_projects`
List all discovered and registered project workspaces and their memory counts on this machine.
