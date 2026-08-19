---
trigger: always_on
description: Institutional memory guideline using Project Memory Cortex MCP tools
---

# Project Memory Rules

Whenever you make key architectural decisions, discover bugs, fix tricky errors, or execute critical deploy/setup commands in this project:
1. **Record key decisions**: Call `memory_add` with type `decision`, `architecture`, `hack`, `command`, or `error`.
2. **Context on session start**: Check `memory_context` to recall institutional memory and past design decisions.
