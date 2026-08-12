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
