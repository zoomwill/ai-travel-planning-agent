# AI Intelligent Travel Planning System — Codex Reconstruction Pack

This repository is a **beginner-friendly reconstruction workspace** for the multi-agent travel planning project shown in the supplied source screenshots.

## Important truth about the source

The screenshots describe a rich architecture and include many code-like examples, but they do **not** provide the original repository, complete dependency lockfile, API credentials, datasets, or verified benchmark logs. Therefore this package aims to:

1. Reproduce the architecture and behavior faithfully.
2. Build a real, runnable implementation in small verified phases.
3. Avoid presenting unverified example metrics as measured results.
4. Use current library APIs when the source pseudocode is outdated.
5. Keep a written record of every deliberate deviation.

## What is already included

- A minimal FastAPI application.
- Liveness and infrastructure readiness endpoints.
- Docker Compose services for PostgreSQL, Redis, and Chroma.
- Validated travel-domain models for requirements and provider results.
- Deterministic mock flight, hotel, attraction, weather, and route providers.
- A deterministic LangGraph Router-to-Planner runtime with no real LLM dependency.
- A local Markdown RAG pipeline backed by the existing Chroma service.
- A project specification reconstructed from the screenshots.
- A phase-by-phase beginner build plan.
- A complete Codex prompt pack.
- Acceptance tests and a debugging playbook.
- An `AGENTS.md` file that tells Codex how to work safely in this repository.

## First action

Do not ask Codex to build the entire system in one message.

Open the repository in Codex, then paste the prompt from:

`docs/prompts/P00_environment_and_repository_audit.md`

After Codex finishes a phase, run the tests, inspect the result, and only then continue to the next prompt.

## Local application check

Start Docker Desktop, start the three P01 services, and then start the application:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/setup_langgraph_persistence.py
uv run uvicorn app.main:app --reload
```

Then open:

- API docs: `http://127.0.0.1:8000/docs`
- Health endpoint: `http://127.0.0.1:8000/health`
- Readiness endpoint: `http://127.0.0.1:8000/ready`

Expected response:

```json
{"status": "ok", "service": "ai-travel-planner"}
```

`/health` and `/health/live` only prove that the web process is alive. `/ready` and
`/health/ready` separately check PostgreSQL, Redis, and Chroma. Readiness returns HTTP 200 only
when all three dependencies respond; otherwise it returns HTTP 503 without exposing passwords,
connection strings, or internal exception messages.

## Local infrastructure

Phase P01 runs PostgreSQL, Redis, and Chroma with Docker Compose. Follow the beginner-safe
startup, verification, logging, port-conflict, stop, and data-reset instructions in
[`docs/08_INFRASTRUCTURE.md`](docs/08_INFRASTRUCTURE.md).

Phase P02 adds the application-side async clients, lifespan ownership, typed settings, and
readiness API. Follow the beginner guide in
[`docs/09_APPLICATION_INFRASTRUCTURE.md`](docs/09_APPLICATION_INFRASTRUCTURE.md).

Phase P03 adds the shared travel vocabulary and deterministic local provider data. It does not
call real travel APIs or an LLM. Read [`docs/10_DOMAIN_MODELS.md`](docs/10_DOMAIN_MODELS.md).

Phase P04 assembles those deterministic provider results into a complete mock travel plan and
exposes `POST /api/v1/plans/mock`. It is an ordinary Python service, not an AI Agent, and makes no
real travel or LLM calls. Follow [`docs/11_PLANNING_MVP.md`](docs/11_PLANNING_MVP.md).

Phase P05 places the same planning service behind a typed LangGraph state and the fixed workflow
`START → Router → Planner → END`. It adds `POST /api/v1/agents/plans` without adding an LLM,
memory, RAG, MCP, or streaming. Read [`docs/12_AGENT_RUNTIME.md`](docs/12_AGENT_RUNTIME.md).

Phase P06 adds deterministic Markdown loading, chunking, offline hash embeddings, persistent
Chroma indexing, and a Retriever Agent. The graph now runs
`START → Router → Retriever → Planner → END`. Follow
[`docs/13_RAG_PIPELINE.md`](docs/13_RAG_PIPELINE.md).

Phase P07 adds durable PostgreSQL checkpoints and explicit, user-approved preference memory. The
graph now runs `START → Memory Context → Router → Retriever → Planner → END`. Existing
`POST /api/v1/agents/plans` callers remain compatible; new thread, state, history, preference-list,
and single-item-delete APIs are documented in
[`docs/14_PERSISTENCE_AND_MEMORY.md`](docs/14_PERSISTENCE_AND_MEMORY.md). Run the explicit setup
script before starting the P07 application for the first time.

Phase P08 uses LangGraph `Send` to fan one request out to deterministic flight, hotel, attraction,
weather, and route search subagents. Custom reducers merge their JSON-safe updates, `Overwrite`
clears old search state on a reused persistent thread, and an aggregator fans the branches back in
before Planner. Read [`docs/15_PARALLEL_SEARCH_SUBAGENTS.md`](docs/15_PARALLEL_SEARCH_SUBAGENTS.md).

Phase P09 adds a deterministic structured quality loop after P08 aggregation. Planner now writes a
draft, Reviewer scores completeness, feasibility, personalization, and budget fit, and conditional
edges either revise the draft or finalize it. The loop has a configurable threshold, an exact
maximum review count, and a standalone LangGraph recursion limit. It still uses no LLM or real
provider. Read
[`docs/16_PLANNER_REVIEWER_REFLECTION.md`](docs/16_PLANNER_REVIEWER_REFLECTION.md).

Phase P10 replaces P06's hash-only child retrieval inside the Agent graph with a versioned hybrid
pipeline: local Sentence Transformer embeddings, deterministic multi-query expansion, BM25,
rank-only RRF fusion, transparent reranking, child-to-parent context, and Redis cache-aside. The
old `travel_knowledge` collection is retained; P10 uses the separate
`travel_knowledge_children_v1` collection. Read
[`docs/17_ADVANCED_RAG.md`](docs/17_ADVANCED_RAG.md) before preparing the model or index.

P10 preparation is deliberately explicit. Ordinary imports, application startup, and pytest do
not download or index a model:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/prepare_rag_model.py
uv run python scripts/index_advanced_knowledge.py
uv run python scripts/index_advanced_knowledge.py
uv run python scripts/evaluate_advanced_rag.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Local diagnostic endpoints are `GET /api/v1/rag/status` and `POST /api/v1/rag/search`. They have
no authentication and are suitable only for local development. The 12 Markdown files are static,
original demo fixtures—not official or live travel data. Always verify current prices, opening
hours, transport notices, weather, accessibility, and availability from an authoritative source.

## Local MCP travel tools

Phase P11 adds a local MCP tool boundary around the same P03 mock providers. It has one STDIO
Server for weather/route and one independent Streamable HTTP Server for flights/hotels/attractions.
The default remains `direct`; no real travel API or LLM tool selection is added. Read the beginner
guide in [`docs/18_MCP_TOOL_LAYER.md`](docs/18_MCP_TOOL_LAYER.md).

To try MCP locally, keep the HTTP Server in its own terminal:

```bash
uv run python -m app.mcp_tools.servers.travel_http
```

Then discover and call all five tools:

```bash
uv run python scripts/check_mcp_tools.py
```

Start FastAPI in explicit MCP mode only after the HTTP Server is ready:

```bash
TRAVEL_SEARCH_BACKEND_MODE=mcp \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Inspect `http://127.0.0.1:8000/api/v1/mcp/status` and
`http://127.0.0.1:8000/ready`. The local MCP HTTP endpoint and diagnostics endpoint have no
authentication and must not be exposed publicly. Stop both terminal processes with Control+C;
the STDIO Server is started and stopped automatically by the client.

## Persistent plan progress streaming

Phase P12 projects one existing persistent LangGraph run into Server-Sent Events (SSE). It does
not run the graph a second time and it does not add an LLM or token streaming. Read the beginner
guide in [`docs/19_SSE_STREAMING.md`](docs/19_SSE_STREAMING.md).

Start Docker and FastAPI as described above, then run this POST request in another terminal:

```bash
curl --noproxy '*' -N \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "user_id": "local-stream-user",
    "requirements": {
      "origin": "Shanghai",
      "destination": "Tokyo",
      "start_date": "2026-09-01",
      "end_date": "2026-09-03",
      "budget": "10000.00",
      "currency": "CNY",
      "travelers": 1,
      "preferences": ["photography", "quiet neighborhoods"]
    },
    "remember_preferences": ["Quiet neighborhoods"]
  }' \
  'http://127.0.0.1:8000/api/v1/agents/threads/local-stream-thread/plans/stream'
```

The first business event is `run_started`. Progress includes safe node, retrieval, five-way
search, and review events. A complete successful stream ends with exactly one `plan_completed`;
an in-stream failure ends with exactly one `error`. Keepalive lines such as `: ping` are transport
comments and do not consume a business event ID.
