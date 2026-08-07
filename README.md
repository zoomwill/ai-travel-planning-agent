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
- A health endpoint.
- Docker Compose services for PostgreSQL, Redis, and Chroma.
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
