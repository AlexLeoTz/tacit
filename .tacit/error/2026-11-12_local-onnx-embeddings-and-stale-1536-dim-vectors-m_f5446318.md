# Local ONNX embeddings and stale 1536-dim vectors made memory_search return nothing

**ID**: `f5446318-651a-4d07-bfd6-38827fbb6872`  
**Type**: `error`  
**Date**: 2026-11-12 13:06:48 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
Search missed real memories because FTS required every word, the local bge model was weak, the 0.52 vector floor was too high, and 51/58 rows still carried OpenAI-width vectors after the provider changed.

## Content
### Symptom / Trigger
`memory_search` looked unreliable on this repository's own store. The concrete reproduction:

```python
bm25_search(conn, "why did we choose async db sessions")  # -> []
bm25_search(conn, "async db sessions")                     # -> 50 rows
```

A natural-language question that contained one word absent from the corpus returned an empty page even though the store held direct matches. In the same store, only 7 of 58 memories had an embedding, all 1536-dim (OpenAI `text-embedding-3-small`), while the configured fallback provider emitted 384-dim local vectors.

### Root Cause Analysis
Four independent causes stacked:

1. **FTS5 was AND-ed.** `bm25_search` built `f"{sanitized}*"` from the whole query. FTS5 treats juxtaposed terms as implicit AND, so `choose async db sessions*` required every token and zeroed the result on the first miss.
2. **The local model was a precision downgrade.** `BAAI/bge-small-en-v1.5` is a 384-dim model trained on short English passages; it scored Tacit's terse engineering notes poorly compared with Gemini.
3. **Stale vectors were silently skipped.** `_numpy_bruteforce` keeps only blobs whose byte length matches the query vector, and `reindex_all(force=False)` only selected `embedded_at IS NULL`. Rows embedded by a previous provider had a non-null `embedded_at`, so a plain reindex never repaired them.
4. **The similarity floor was tuned for the old model.** The 0.52 cosine threshold discarded Gemini-style document/query pairs that score lower while still being the right memory.

`tags` was also accepted by `memory_search` but never applied to the BM25 query, so a tagged search returned untagged rows.

### Resolution
- Removed the local ONNX provider entirely (also `fastembed`, the model cache and `ensure_local_model`).
- Made Gemini `gemini-embedding-001` the default provider at an explicit 768 dimensions; OpenAI is an explicit opt-in fallback.
- Reworked `bm25_search` to OR prefix terms, apply the `tags` filter, and fall back to a per-term LIKE scan when FTS returns nothing.
- Lowered the vector floor to a configurable `TACIT_VECTOR_MIN_SIMILARITY` default 0.30 and added the same tags filter to vector retrieval.
- `reindex_all(force=False)` now re-embeds rows whose blob width differs from the active provider, and `count_stale_embeddings` counts missing as well as width-mismatched rows.

### Prevention
When changing embedding providers, run `tacit reindex --force`; a plain `tacit reindex` now repairs width mismatches too. Any future query-shape change must keep an OR-style recall path: FTS5 implicit AND is a false-negative factory for agent-authored questions.

### Validation
Added `test_bm25_or_terms_recall_a_natural_language_question`, `test_tags_filter_is_applied` and `test_reindex_without_force_also_repairs_wrong_width_vectors`. The full suite passes (385 tests), including the rewritten provider tests.

## Taxonomy & Relations
- **Tags**: search, embeddings, fts5, vector, reliability
- **Scope**: src/search/embeddings.py, src/search/hybrid.py, src/core/storage.py, tests/test_hybrid_search.py
- **Parents**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`
- **Children**: None
- **Related**: None

---
*Content Hash*: `8fde5e941005af2e83abe8a202c3076f544cc986dd1d404df686dc47a7f67d9c`  
*Merkle Root*: `fb052a91e3470523d67914ed00318db0dcefc28e4fc19fbf9c0266d28e6f319b`
