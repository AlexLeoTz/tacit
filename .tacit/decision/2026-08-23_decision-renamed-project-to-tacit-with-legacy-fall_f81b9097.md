# Decision: Renamed Project to Tacit with Legacy Fallbacks

**ID**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`  
**Type**: `decision`  
**Date**: 2026-08-23 11:04:35 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
Rename Project Memory Cortex to Tacit with full backward-compatibility fallbacks.

## Content
Renamed Project Memory Cortex (PMC) to Tacit. Implemented backward-compatibility fallbacks in Config:
- Checks legacy `.project-memory/` if `.tacit/` does not exist.
- Migrates and reads legacy `pmc_projects.json` and `pmc_update_cache.json` automatically.
- Falls back to `PMC_DUAL_WRITE` and `PMC_NO_PATH_VALIDATION` environment variables.
- Keeps `pmc` entry point alias in `setup.py` alongside the new `tacit` CLI.
Updated templates, README documentation, and ASCII logo.

## Taxonomy & Relations
- **Tags**: rename, refactor, compatibility, config
- **Scope**: setup.py, src/utils/config.py, src/cli/main.py, src/mcp/server.py, src/export/templates.py
- **Parents**: None
- **Children**: None
- **Related**: None

---
*Content Hash*: `854fc65e562120d8f0467a7c1ef6d33f281a5cda2233930dd53dd0ab2e14031c`  
*Merkle Root*: `5e58c47dd9249a761e15e7d15cdc99504a9dcbf4f96ffd1b45fee6b429461113`
