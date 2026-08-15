# Phase P10 — Advanced Hybrid RAG

This chapter explains P10 from a beginner's point of view. “RAG” means retrieval-augmented
generation: before Planner creates a plan, the program looks up a small amount of relevant local
knowledge and passes that text to Planner. P10 still uses deterministic mock travel providers and
a deterministic Reviewer. It does not call an LLM.

## What changed from P06?

P06 split four Markdown files into small pieces, converted words into 128-number hash vectors,
and queried the `travel_knowledge` Chroma collection. Hash vectors are deterministic and useful
for an offline starter, but they mostly notice shared word forms.

P10 keeps that old collection and adds a separate pipeline:

```text
validated request
→ deterministic query variants
→ semantic dense search + BM25 sparse search
→ Reciprocal Rank Fusion (RRF)
→ child results grouped by parent
→ deterministic parent reranker
→ complete parent context
→ Redis cache
→ LangGraph State
→ Planner → Reviewer
```

The new collection is `travel_knowledge_children_v1`. Keeping the P06 collection avoids a
destructive migration and makes the version boundary visible.

## Model and index preparation

Start Docker Desktop and the local services first:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/check_infra.py
uv run python scripts/setup_langgraph_persistence.py
```

Model preparation is a separate, explicit network operation:

```bash
uv run python scripts/prepare_rag_model.py
```

It loads `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` on CPU and prints the
reported embedding dimension. It does not connect to Chroma or Redis. No model is downloaded at
module import, application startup, or ordinary pytest time.

Build the index only after model preparation succeeds:

```bash
uv run python scripts/index_advanced_knowledge.py
```

The script loads all committed Markdown fixtures, creates parents and children, embeds only the
children, upserts them to Chroma, writes parents to namespaced Redis keys, and writes a generated
local manifest. Run it twice to check idempotency: counts and corpus fingerprint must stay equal.
Generated manifest data and model weights are ignored by Git because both are reproducible local
artifacts.

## Parent and child documents

A parent is a readable Markdown section. Headings define the preferred boundary; only an
overlong section uses a 1,200-character fallback window with 150-character overlap. Parents keep
source, city, title, heading path, document type, language, content hash, and index version.

A child is a smaller search unit made inside exactly one parent. Its maximum size is 350
characters with 50-character overlap. Smaller units help search find a focused passage. Planner,
however, needs surrounding explanation, so P10 maps the winning child back to its complete parent.
Several overlapping children from one parent become one context, not several duplicate contexts.

Parent and child IDs use canonical JSON plus SHA-256. Python's built-in `hash()` is not used,
because its output is not a safe persistent identity. A content or version change produces a new
ID and corpus fingerprint.

The current local demo corpus has 12 Markdown files, 36 parent sections, and 77 children. These
are original static fixtures, not live or official travel content.

## Semantic dense retrieval

Sentence Transformers turns a document or query into 384 floating-point numbers called an
embedding. Texts with similar meaning can be closer even if they do not share every exact word.
P10 prefers the current public `encode_document()` and `encode_query()` methods, normalizes their
vectors, and passes query embeddings explicitly to Chroma `Collection.query()`.

Chroma uses cosine distance in the new collection. Only the cosine space is configured; HNSW's
other settings remain Chroma defaults because this tiny fixture does not justify performance
tuning. Embeddings stay in Chroma and never enter LangGraph State, PostgreSQL checkpoints, Redis
cache values, or HTTP responses.

When destination is present, the adapter constructs a validated `where={"city": ...}` filter. It
never forwards an arbitrary user dictionary. If a filtered result list is too short and fallback
is enabled, it performs one explicit unfiltered query and records that fact in diagnostics.

## Sparse retrieval and BM25

Sparse search looks for lexical evidence. P10 uses `rank-bm25`'s `BM25Okapi`. The same deterministic
tokenizer is used for documents and queries: it case-folds English tokens and gives Chinese text a
character and bigram fallback without downloading a segmenter. City filtering happens before a
candidate is returned. Score ties use child ID, so repeated input has stable output.

BM25 score and Chroma distance measure different things on unrelated scales. Adding the raw
numbers would make one scale dominate for accidental reasons. P10 therefore keeps raw scores
inside their own retriever and combines ranks instead.

## Deterministic multi-query

One user request is expanded into at most four stable variants. The original query is always
first. Later variants combine the validated destination, current preferences, and remembered
preferences, remove exact duplicates, preserve order, and add no invented place or hard
constraint.

This is an interface for future LLM query expansion, but the current implementation is not LLM
Multi-Query. It uses no network, random value, model prompt, or current time.

## Reciprocal Rank Fusion

RRF combines result positions rather than incomparable raw scores:

```text
RRF(document) = sum(1 / (k + rank))
```

Ranks start at 1 and the configured constant is `k=60`. A child that appears in several dense,
sparse, or query-variant rankings accumulates several contributions. Equal RRF scores use stable
child ID order. The value 60 is a conventional default, not a measured optimum for this demo.

## Second-stage reranking

After grouping child evidence by parent, the deterministic reranker calculates a second score:

```text
0.35 × normalized RRF
+ 0.20 × exact city match
+ 0.20 × query-token coverage
+ 0.10 × current-preference coverage
+ 0.10 × remembered-preference coverage
+ 0.05 × title/heading coverage
```

These fixed weights are transparent, untrained, and not an LLM reranker. Stable parent ID breaks
ties. If reranking raises an error, P10 falls back to RRF parent order and records `reranker` in
diagnostics instead of failing the whole request.

A future Qwen integration can implement the existing `QueryExpander` or `CandidateReranker`
Protocol. That future phase must validate structured output, apply timeouts, add deterministic
test doubles, and keep model/client objects out of State. P10 does not implement it.

## Parent store and cache-aside

Parents are reconstructable index data. Redis keys use this namespace:

```text
rag:parent:advanced-v1:{parent_id}
```

The same parent set is written to a local versioned manifest. Retrieval tries Redis first. If one
Redis parent read fails or exceeds the application timeout, the running store switches directly
to the local manifest for the remaining parents. This does not affect P07 user memory or
PostgreSQL checkpoints.

The retrieval cache stores only the final parent-level JSON result. Its key is canonical JSON plus
SHA-256 over pipeline version, corpus fingerprint, embedding backend/model, query variants,
metadata filter, all retrieval limits, and RRF k. The prefix is
`rag:cache:advanced-v1:` and the default TTL is 3,600 seconds. A corpus/config change naturally
creates a different key.

Cache-aside means: try GET; on miss run retrieval; then `SET ... EX 3600`. A hit skips dense,
BM25, fusion, parent fetch, and reranking. Corrupt JSON deletes only that exact key and reruns. A
Redis error sets `cache_status=unavailable` and continues. No P10 code uses `FLUSHDB`, `FLUSHALL`,
or a broad key scan.

## Versioning and stale cleanup

The indexer reads the exact current-version child IDs, compares them with the new manifest, prints
the stale count before deletion, and calls Chroma delete only with the resulting explicit IDs.
Old parent IDs come only from the previous same-version local manifest and are deleted by explicit
Redis key. It never resets Chroma and never deletes the old `travel_knowledge` collection.

## LangGraph and failure behavior

The graph still has one node named `retriever`. The lifespan creates one semantic model, BM25
index, manifest, parent store, cache, and advanced retriever, then injects the retriever while
compiling the graph. Those objects never enter State.

State keeps only final parent contexts, query variants, parent IDs, JSON-safe diagnostics, and a
safe retrieval error. On a reused thread, `Overwrite` replaces every old retrieval field. The P09
revision loop does not retrieve again. Planner and Reviewer use the same final parent context.

If only dense or sparse retrieval fails, the other can continue. If both fail, the retriever
returns no fabricated context and `retrieval_unavailable`; P08 mock search may still produce a
degraded plan, and Reviewer receives the non-critical failure. `/health` remains a liveness check
when an index is absent. The RAG status says `indexed=false`, and direct RAG search returns a
sanitized 503.

## Local diagnostic API

Start the application after indexing:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check status:

```bash
curl --noproxy '*' --fail-with-body --silent --show-error \
  http://127.0.0.1:8000/api/v1/rag/status
```

Search:

```bash
curl --noproxy '*' --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "query": "东京安静、适合街头摄影的社区",
    "destination": "Tokyo",
    "preferences": ["photography", "avoid crowds"],
    "top_k": 4
  }' \
  http://127.0.0.1:8000/api/v1/rag/search
```

These endpoints expose parent context and bounded diagnostics, not embeddings, cache keys, client
objects, local model paths, tracebacks, or secrets. They have no authentication and are for local
development only.

## Offline evaluation

Run:

```bash
uv run python scripts/evaluate_advanced_rag.py
```

The fixed dataset has 24 English and Chinese queries with human-written parent relevance labels
from 0 to 3. It evaluates dense-only, BM25-only, hybrid RRF, and hybrid reranked at parent-level
`K=4`. Evaluation uses 4 because the production configuration returns at most four parents; the
phase prompt's `K=5` was a suggestion.

- Precision@K: what fraction of the K result slots contain a relevant parent.
- Recall@K: what fraction of all labeled relevant parents were retrieved.
- MRR@K: reciprocal position of the first relevant parent.
- NDCG@K: graded relevance reward discounted for later ranks and normalized by ideal order.

The script calculates formulas locally and macro-averages queries. It does not use retriever output
to generate ground truth and does not require one mode to win. Actual numbers are in
[`evaluation/P10_RAG_EVALUATION.md`](evaluation/P10_RAG_EVALUATION.md) and
`reports/p10_rag_evaluation.json`. On this small run, hybrid reranked improved MRR/NDCG over the
dense baseline but had lower Precision/Recall. That mixed result is not evidence of production
quality.

## Verification commands

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

Ordinary pytest never starts Docker or downloads a model. Integration tests are explicitly
enabled only after Docker, model preparation, and indexing. P10 is complete only when the model
loads, indexing is repeatable, stale exact deletion is demonstrated, evaluation reports are
generated, HTTP cache/filter/Agent flows work, Redis fallback is observed, all quality commands
pass, and P06/P07/P08/P09 data and behavior remain intact.
