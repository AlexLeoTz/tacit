# Replaced local ONNX embeddings with Gemini gemini-embedding-001 at 768 dimensions

**ID**: `3de9894f-9865-4b51-b6f9-d405d3f49e1f`  
**Type**: `decision`  
**Date**: 2026-11-12 13:06:48 E. Africa Standard Time  
**Impact**: `high`  
**Status**: `active`  
**Author**: `ai-agent`  

## Summary
Tacit now uses GEMINI_API_KEY and gemini-embedding-001 as its default embedding engine, with explicit outputDimensionality=768, manual normalization and OpenAI only as an opt-in alternative.

## Content
### Context & Problem Statement
Tacit's provider chain was OpenAI -> Gemini -> local ONNX. In practice most machines had no key, so search fell back to a 384-dim local model whose recall on terse engineering notes was poor, and whose cache could be missing, sandboxed or corrupt. The product requirement is a reliable semantic index with a single, explicit key: `GEMINI_API_KEY`.

### Alternatives Evaluated & Rejected
1. **Keep local ONNX as zero-config fallback.** Rejected: it produced the unreliable search this change set out to fix, and its ~50 MB cache was the source of the sandbox retry storms.
2. **Gemini 3072-dim default.** Rejected: 3x storage for negligible MTEB gain (67.99 at 768 vs 68.17 at 1536). 768 is Google's recommended quality/storage point.
3. **Drop OpenAI entirely.** Rejected: existing teams standardised on OpenAI keep a migration path, and the wire code already existed. It is opt-in rather than auto-preferred so a stray `OPENAI_API_KEY` cannot silently override Gemini.

### Solution & Rationale
`EmbeddingService` resolves once per process (sticky): `TACIT_EMBED_PROVIDER` if set, else Gemini when `GEMINI_API_KEY` exists, else OpenAI, else none. Gemini requests use `batchEmbedContents`, `taskType=RETRIEVAL_DOCUMENT` for stored title/tags/summary and `RETRIEVAL_QUERY` for the search query, and `outputDimensionality=768`. Because `gemini-embedding-001` requires manual normalization below 3072 dims, both document and query vectors are L2-normalized before storage/search. The API key travels in `x-goog-api-key`, never the URL.

`gemini_dim()` supports `TACIT_GEMINI_DIM` (128-3072) and omits the field for legacy models such as `text-embedding-004`. A response whose width differs from the expected width raises `EmbeddingUnavailable` instead of storing unusable vectors.

### Trade-offs & Consequences
- Semantic search now needs network access and a paid/free Gemini quota; without a key search is keyword-only, not silently degraded.
- Changing provider or dimension invalidates existing vectors; `tacit reindex` repairs widths and `--force` rebuilds all.
- The provider is intentionally sticky: a key appearing or disappearing mid-session cannot switch embedding spaces.

### Validation
`tests/test_embeddings_providers.py` covers provider precedence, the exact `batchEmbedContents` body (task types, `outputDimensionality`, header-only key), dimension mismatch rejection, 429 retry/backoff, pacing and redaction. `test_move` and the old local-cache tests were removed. Full suite: 385 passed.

## Taxonomy & Relations
- **Tags**: embeddings, gemini, gemini-embedding-001, onnx, search
- **Scope**: src/search/embeddings.py, src/cli/main.py, setup.py, README.md, tests/test_embeddings_providers.py
- **Parents**: `f81b9097-0cd2-4087-b1c2-5a87bb5dd263`, `f5446318-651a-4d07-bfd6-38827fbb6872`
- **Children**: None
- **Related**: None

---
*Content Hash*: `415595ec7f25cd5af04e2705deb5a84c2110ca8b6a489498d1b6f3a99a7f86ab`  
*Merkle Root*: `7eba3188d4b1079c36637031f6a213a9f2143b4931549bbec90122327fa9a8b9`
