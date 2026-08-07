# Phase P02 Application Infrastructure Guide

Phase P01 starts PostgreSQL, Redis, and Chroma in Docker. Phase P02 teaches the FastAPI process
how to check those services safely. It does not create business tables, store vectors, flush
Redis, or add any AI workflow.

## Mental model for a beginner

The FastAPI process owns one resource container while it is running:

1. FastAPI starts its lifespan.
2. The lifespan creates a SQLAlchemy async engine, a Redis async client, and a lazy Chroma
   provider.
3. Request dependencies read those same objects from `request.app.state.resources`.
4. FastAPI stops its lifespan and attempts every public cleanup operation.

PostgreSQL and Redis client constructors are lazy, so creating them does not prove their servers
are reachable. Chroma's official `AsyncHttpClient` factory does perform network requests, so the
provider delays that factory until readiness first needs it. This lets the web process start and
keeps liveness available even when Chroma is down.

## Local settings

Copy `.env.example` to `.env` only if `.env` is missing:

```bash
cp -n .env.example .env
git check-ignore -v .env
```

The second command must show that `.gitignore` ignores `.env`. Never commit `.env`. Important
P02 variable groups are:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`
- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_SSL`
- `INFRASTRUCTURE_TIMEOUT_SECONDS`

`POSTGRES_PASSWORD` is loaded as Pydantic `SecretStr`. The PostgreSQL connection URL is built with
SQLAlchemy's structured `URL.create()` API, so punctuation in a password is encoded safely and
normal representations hide the value. The default readiness deadline is two seconds per
service. Use a positive number if local startup needs a different deadline.

## Start and verify

Start Docker Desktop first. From the repository root, validate and start P01 services:

```bash
docker compose config --quiet
docker compose up -d --wait --wait-timeout 120
docker compose ps
uv run python scripts/check_infra.py
```

Then start FastAPI in a separate terminal:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify liveness and readiness:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/health/live
curl --fail --silent --show-error http://127.0.0.1:8000/ready
```

The first two endpoints return HTTP 200 when the web process is alive and never contact Docker
services. `/ready` checks all three services concurrently:

```json
{
  "status": "ready",
  "services": {
    "postgresql": {"status": "ok"},
    "redis": {"status": "ok"},
    "chroma": {"status": "ok"}
  }
}
```

If one or more checks fail or time out, the response uses HTTP 503, changes the overall status to
`not_ready`, and still shows every service as `ok` or `error`. It deliberately omits raw exception
messages, host details, connection URLs, passwords, and API keys. `/health/ready` is a compatible
alias for `/ready`.

## Unit and integration tests

Normal tests use local fakes and do not require Docker:

```bash
uv run pytest -q
```

The real Docker integration test is opt-in:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -q -m integration
```

Without `RUN_INTEGRATION_TESTS=1`, the integration test is explicitly skipped. After the variable
is set, a connection failure is a real test failure and is not converted into a skip.

## Stop cleanly

Press Control-C in the Uvicorn terminal. FastAPI then closes Redis, disposes the SQLAlchemy engine,
and releases the application reference to Chroma. Stop Docker containers while retaining all
named-volume data with:

```bash
docker compose stop
```

Do not use `docker compose down -v` as a normal stop command; it deletes local database, Redis, and
Chroma volume data.

## Troubleshooting

- `/health` is HTTP 200 but `/ready` is HTTP 503: the application process is alive, but at least
  one required service is unavailable or exceeded the configured timeout. Run
  `docker compose ps`, `uv run python scripts/check_infra.py`, and inspect the relevant Compose log.
- PostgreSQL is `error`: confirm the container is healthy and `.env` uses the initialized database
  credentials. Initialization variables only apply to an empty PostgreSQL data directory.
- Redis is `error`: confirm the container is healthy and `REDIS_HOST`, `REDIS_PORT`, and `REDIS_DB`
  point to the local service.
- Chroma is `error`: confirm port 8001 is reachable and the client/server versions remain aligned.
  No collection, vector, or reset operation is part of P02.
- A port is occupied: use the `lsof` commands in `docs/08_INFRASTRUCTURE.md` before changing `.env`.

Chroma Python client 1.5.9 does not expose `close()`, `aclose()`, or `stop()` on its public
`AsyncClientAPI`. Its internal HTTP component has cleanup behavior, but P02 does not reach into
private attributes. The lifespan therefore releases its own client reference and documents this
upstream cleanup limitation instead of guessing an unsupported API.
