# P18 Railway bootstrap reliability follow-up

Date: 2026-09-08 (local). Started from clean committed P18 `b249bb5`.
No commit, push, P19, cloud resource change or real Auth0/Qwen/Duffel/LiteAPI call.

## Outcome — important capacity limitation remains

The focused batching, lifecycle and diagnostics changes are implemented and tested. However,
**1 GiB is not verified usable**: the actual local capped container was OOM-killed with exit137
at `embedding_load_start`, before any indexing batch. This is a real local failure, not a passed
acceptance. The user-reported Railway failure may share that cause, but its OOM/exit metadata
was not independently accessed; do not label the Railway root cause proven.

A separately explicit **local 2 GiB comparison** passed fresh indexing, readiness, planning,
continued readiness, restart and graceful shutdown. Observed kernel cgroup `memory.peak` was
**1,543,884,800 bytes (about 1.44 GiB)**. This includes cgroup memory charges/page cache, not
only Python RSS. It is neither a Railway measurement nor a guaranteed minimum production size.
The local image architecture was arm64; another platform/load can have a different working set.

Railway remains unchanged at its user-reported 1 GB limit. Choosing cloud capacity requires
the user's platform/billing decision. No automatic upgrade, model switch, quantization, weaker
model, public Chroma endpoint or `/health` readiness workaround was introduced.

## Exact startup and batching

```text
Settings + PORT validation
  → bootstrap inner owner
      → PostgreSQL connection/advisory lock + official schema setup
      → one pinned SentenceTransformer load (deployment encode batch=8)
      → unchanged deterministic P10 corpus
      → private Chroma collection + existing IDs
      → stable corpus-order missing-only batches: 8 × 9, then 5 (fresh 77)
      → exact count check: 77
      → Redis parent documents → local reproducible manifest
      → leave resource contexts and return (model/vector/corpus locals released)
  → one cyclic gc.collect() boundary
  → memory_released → complete → flushed PASS deployment prerequisites
  → create_app → one normal runtime RAG model load → Uvicorn → /ready
```

- Confirmed previous behavior: one upsert call received every missing child. The adapter sent
  its full input to one embedding call, retaining the resulting vectors until the write.
- Important nuance: Sentence Transformers internally defaults to batch_size32, so the old call
  was **not necessarily a 77-row simultaneous model compute batch**.
- New `RAG_BOOTSTRAP_BATCH_SIZE`: default8, integer range1–32. Boolean/floating values are
  rejected; integer environment strings are accepted. Both deployment upsert and encode use it.
- Zero missing IDs means zero upserts. Restart skips successfully written partial batches;
  a complete index is not rewritten. The set determines membership only, not insertion order.
- The model, pinned revision, dimension384, corpus, child IDs, collection, documents, metadata,
  normalization, precision, query path, ranking and P10 evaluation code remain unchanged.
  Runtime and the normal P10 indexer do not receive the deployment-only encode override.
- Python3.11-compatible `islice` is used without a new dependency or minimum-version change.

## Numeric and lifetime evidence

The offline tests compare the real adapter's complete record payload against a one-call reference
using deterministic test embeddings. IDs/documents/metadata/test vectors match exactly; no
duplicate IDs are generated. This alone is not a real semantic-model verification.

An additional explicit host-side test loaded the cached pinned model once, with networking
disabled, and compared all77×384 real vectors from default encoding against stable batches of8.
`numpy.allclose(rtol=1e-5, atol=1e-6)` passed; measured maximum absolute difference was
`8.568167686462402e-08`. This supports numerical equivalence, **not bitwise identity** or a new
P10 quality/performance metric. No document text or vectors were output.

The vector store owns the bootstrap backend locally; Chroma's collection is configured with
`embedding_function=None`. The inner coroutine ends before collection of model/library cycles
and before application creation. Tests create cyclic model references, observe dead weakrefs,
then invoke the actual runtime RAG factory and prove exactly one subsequent model load with
normal encode defaults. No two bootstrap/runtime models are intentionally retained together.
GC is not an OS allocator/RSS reset; no private PyTorch APIs or per-request collection is used.

Current installed Transformers source explicitly discards legacy `low_cpu_mem_usage` and
`offload_state_dict` keywords. They were not added as placebo configuration. Precision changes,
model substitutions and a new offloading architecture are outside this focused patch.

## Diagnostics and findings

Every new bootstrap line is flushed, uses an allowlisted stage and optional bounded integer
`batch`, `batches`, `children` fields. There are starts/completions around PostgreSQL, model,
corpus, Chroma connect/existing IDs/batches/count, Redis, manifest and memory release.
Normal escaping Python exceptions are wrapped into safe phase/class fields:

```text
FAIL deployment startup phase=bootstrap error_type=ConnectError
```

The entry point does not format exception text, repr, traceback, DSN, password, token or chunk
content. Cancellation remains cancellation. A kernel kill cannot execute that Python handler.
The local checker additionally reads only OOMKilled/exit code and a validated last stage on failure.

| Severity | Finding | Status |
|---|---|---|
| Critical | None identified in this focused diff | Not a comprehensive security audit |
| High / operational | Local1GiB container OOM before indexing/model load completion | **Unresolved at1GiB**; local2GiB passed; Railway capacity/exit evidence needs user decision |
| Medium | All missing children were submitted to one adapter operation; encode default32 | Fixed: deployment batch8, bounded sequential writes and explicit encode batch |
| Medium | Startup exceptions were collapsed to an uninformative generic line | Fixed: flushed stages plus phase/class only; no exception-value logging |
| Medium / preventive | Model/vector lifetime across the bootstrap/runtime boundary was not tested | Explicit owner/GC boundary plus cyclic weakref and actual runtime-factory regression |
| Test harness | Existing integration tests inherited newly enabled local Auth0 mode and got401 | Fixed in tests only: demo auth unless real Auth0 integration gate is explicit |

Remaining risks: kernel kills cannot log a final failure; first model load has a large baseline
working set independent of indexing batch size; native allocator behavior and architecture/load
affect peak; partially indexed writes are resumed, not rolled back; cross-region sequential
batches may increase startup latency. No exact Railway latency or memory minimum was measured.

Railway's project/environment private mesh supports communication across services; crossing
regions is not, by itself, evidence of this crash. Keep private PostgreSQL/Redis/Chroma and
`/ready`. No service domain, region, volume, healthcheck path or cloud setting was changed.

## Executed verification

| Command / check | Actual result |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS,382 files |
| `uv run mypy app` | PASS,170 source files |
| `uv run pytest tests/deployment tests/rag/test_advanced_embeddings.py -q` | 52 passed |
| `uv run pytest -q` | 754 passed,17 skipped |
| `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q` | 11 passed, 1 skipped, 759 deselected |
| Local pinned-model comparison | PASS,77×384, tolerance and observed difference above |
| `docker build -t travel-planner:p18 .` | PASS; final image config ID starts `d1188ead32f6` |
| Fresh-index default1GiB | **FAIL**,OOMKilled=true,exit137,last stage embedding_load_start |
| Fresh-index explicit2GiB | PASS,77 children,10 batches, /ready200, stable probes, demo plan,restart,shutdown |

The first integration attempt was2 failed/9 passed/1 skipped due to401 in the old token-free
fixtures. The application correctly enforced the local authentication setting. Ordinary test
auth isolation was corrected without modifying application auth. No real Auth0 request occurred.
Other development failures (line lengths and using a Python3.12-only batching helper) were fixed
before final checks. BuildKit's existing warning about `ENV AUTH_MODE` is a name-based warning
for the public enum value, not a secret value; no credential build arguments were added.

Actual2GiB checker output:

```text
PASS fresh index: 77 children, 10 batches (9 x 8 + 5)
PASS container: health, readiness, prepared RAG and deterministic Agent plan
PASS container restart: same RAG status; idempotent bootstrap
INFO observed cgroup memory.peak bytes: 1543884800
INFO local image architecture: arm64; API limit=2147483648 bytes
PASS container shutdown: application resources closed after SIGTERM
INFO image size bytes: 796048963
INFO image runtime user: 10001:10001
PASS image environment: no backend credential variables
PASS cleanup: temporary API container removed; named volumes retained
PASS cleanup: isolated Chroma container/tmpfs removed; existing data untouched
```

## Manual verification and next decision

These commands build locally and test isolated first indexing. Start Docker Desktop and existing
core services first. The default1GiB reproduction currently fails; do not silently substitute the
2GiB comparison and report the1GiB gate green.

```bash
docker build -t travel-planner:p18 .
uv run python scripts/check_deployment.py --fresh-index
uv run python scripts/check_deployment.py --fresh-index --memory-mib 2048
uv run pytest tests/deployment tests/rag/test_advanced_embeddings.py -q
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
git diff --check
git status --short
```

The user should inspect actual Railway OOM/exit events, then decide whether to adjust API memory
after checking costs. If a new deployment is authorized later, observe the complete stage
sequence, actual `/ready` success and sustained behavior. This run neither redeployed Railway
nor demonstrated that the existing1GB service is fixed. Do not expose private services or weaken
readiness to get a green badge. No real LLM/travel-provider smoke is needed for this fix.

Suggested commit only: `fix: bound deployment RAG bootstrap memory`.

## Final files and cleanup

12 modified tracked files and 4 new files (16 total), all unstaged:

```text
 M .env.example
 M app/core/config.py
 M app/deployment/bootstrap.py
 M app/deployment/start.py
 M app/rag/embeddings.py
 M docs/25_AUTH_AND_DEPLOYMENT.md
 M docs/implementation-notes.md
 M scripts/check_deployment.py
 M tests/conftest.py
 M tests/deployment/test_bootstrap.py
 M tests/deployment/test_checker.py
 M tests/rag/test_advanced_embeddings.py
?? app/deployment/diagnostics.py
?? docs/P18_BOOTSTRAP_FIX_REPORT.md
?? tests/deployment/test_bootstrap_batches.py
?? tests/deployment/test_start.py
```

`git diff --check` passed; no staged paths; HEAD remains `b249bb5`. Actual `.env` is still
ignored and was not printed or edited. Both failed/successful acceptance runs removed their
own temporary API and Chroma containers; the rebuildable tmpfs test indexes are discarded.
Existing postgres_data, redis_data, chroma_data, prometheus_data and grafana_data named volumes
remain. Existing PostgreSQL/Redis are healthy and Chroma remains running on loopback8001 with
its independent healthcheck passing. No image/data-volume deletion, commit, push or P19.

Official API references:

- [Sentence Transformer encoding parameters](https://sbert.net/docs/package_reference/sentence_transformer/model.html)
- [Transformers model loading](https://github.com/huggingface/transformers/blob/main/docs/source/en/models.md)
- [Railway private networking](https://docs.railway.com/networking/private-networking/how-it-works)
