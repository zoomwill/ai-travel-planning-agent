# Full-System Acceptance Criteria

The reconstruction is complete only when all mandatory checks pass.

## Environment and API

- Fresh clone follows README successfully.
- `.env.example` contains no real secrets.
- Docker services start reproducibly.
- Health endpoints and request validation work.
- Complete requests produce plans; incomplete requests produce focused questions.

## Graph

- Each request has a thread ID.
- Same-thread state resumes; new threads are isolated.
- Simple lookup and full planning route differently.
- Failed review revises; maximum iteration stops.
- State history is inspectable.

## Parallelism

- Independent branches execute concurrently.
- Reducers merge results without overwrite.
- One branch failure retains other results and records a structured error.

## RAG

- Parent and child chunks are linked.
- Dense and sparse retrieval both work.
- RRF is deterministic on fixtures.
- Cache hits avoid repeated retrieval.
- Offline evaluation outputs Recall@K, Precision@K, MRR and NDCG@K.

## MCP

- stdio and HTTP servers expose tools.
- Client discovers tools from both.
- Duplicate names, invalid input and timeouts are handled.

## Memory and streaming

- Stable preferences persist across threads.
- Temporary preferences remain thread-local unless saved.
- Contradictions follow a defined policy.
- SSE emits ordered start, content, completion and error events.
- Disconnect cancels unnecessary work.

## Observability and honesty

- Logs include request and thread IDs and redact secrets.
- Prometheus metrics are exposed.
- Deterministic end-to-end test passes.
- No source performance claim is presented as measured without an artifact.
