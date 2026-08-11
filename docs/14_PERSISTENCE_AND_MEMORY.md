# P07 — Durable LangGraph Persistence and Explicit User Preference Memory

P07 gives the deterministic travel graph two different kinds of PostgreSQL-backed memory. It
still does not call an LLM or a real travel provider.

```text
POST /api/v1/agents/threads/{thread_id}/plans
        |
        | config: thread_id
        | context: user_id + remember_preferences
        v
START -> Memory Context -> Router -> Retriever -> Planner -> END
           |                                      |
           v                                      v
  PostgreSQL Store                      PostgreSQL Checkpointer
  user preferences                      graph state and history
```

## 20 beginner concepts

1. **Persistence** means data remains after Python stops. P07 uses the existing local PostgreSQL
   container for this durability.
2. A **checkpointer** saves graph state after graph steps. P07 uses the official
   `AsyncPostgresSaver`.
3. A **checkpoint** is one saved snapshot. One run creates several checkpoints, not only a final
   plan.
4. A **thread** is a sequence identified by `thread_id`. Reusing an ID continues its saved state;
   another ID creates an independent sequence.
5. `thread_id` is passed in LangGraph's `configurable` config. It is not copied into
   `TravelPlanState` as an ordinary business field.
6. **Short-term thread memory** means the state and history for one thread.
7. A **store** saves data independently from a thread. P07 uses the official
   `AsyncPostgresStore`.
8. **Long-term preference memory** can be read by another thread for the same user.
9. `user_id` selects a local namespace. It is not login or authentication.
10. A **namespace** works like a folder. P07 uses `(user_id, "travel_preferences")`, so two users
    do not share preference records.
11. **Runtime context** contains run-only values that should not become graph state. P07's typed
    dataclass contains `user_id` and `preferences_to_remember`.
12. **Explicit memory** means only values in `remember_preferences` are saved. Ordinary
    `requirements.preferences` is never saved automatically.
13. Destination, dates, budget, traveler count, and other trip fields are never promoted into
    long-term preference memory.
14. **Normalization** makes case and whitespace variants map to one comparison value.
15. A deterministic **preference ID** is derived from `user_id` plus the normalized value. The raw
    user ID and preference are not placed in that ID.
16. **Upsert** means insert if missing, otherwise update. It preserves `created_at` while changing
    `updated_at` and `source_thread_id`.
17. **Lifespan ownership** means FastAPI opens one saver and one store when the app starts and
    closes them when it stops. They are not created per request.
18. **Setup** creates or migrates LangGraph's own tables. The explicit script is idempotent;
    importing the app never silently runs migrations.
19. **Strict MessagePack** only reconstructs types derived from typed graph schemas. Pickle
    fallback is explicitly disabled because loading untrusted pickle can execute code.
20. **Integration tests are opt-in** because they need Docker. Ordinary tests use
    `InMemorySaver` and `InMemoryStore` and do not contact PostgreSQL.

## Files to read first

- `app/graphs/state.py`: durable graph fields, including `remembered_preferences`.
- `app/graphs/context.py`: run-only user and explicit-memory input.
- `app/graphs/nodes/memory_context.py`: save explicit preferences, then load one user namespace.
- `app/memory/models.py`: one stored preference record.
- `app/memory/preferences.py`: normalization, category, ID, upsert, list, and delete logic.
- `app/core/persistence.py`: official PostgreSQL saver/store lifecycle.
- `app/api/routes/persistence.py`: thread, history, and preference HTTP boundaries.

## First-time local setup

Start Docker Desktop first. From the repository root run:

```bash
docker compose up -d --wait --wait-timeout 120
uv sync
uv run python scripts/setup_langgraph_persistence.py
```

Expected output:

```text
PASS LangGraph checkpointer: schema is ready
PASS LangGraph preference store: schema is ready
```

The setup command is safe to run again. It only applies LangGraph's official migrations; it does
not create travel-business tables, truncate data, or delete a volume.

Start FastAPI:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Create a persistent plan

This saves only `quiet neighborhoods`. The `photography` value remains current-trip input and is
not long-term memory.

```bash
curl --noproxy '*' --fail --silent --show-error \
  -X POST http://127.0.0.1:8000/api/v1/agents/threads/demo-thread-1/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "demo-user",
    "requirements": {
      "origin": "Shanghai",
      "destination": "Tokyo",
      "start_date": "2026-09-01",
      "end_date": "2026-09-03",
      "budget": "10000.00",
      "currency": "CNY",
      "travelers": 1,
      "preferences": ["photography"]
    },
    "remember_preferences": ["quiet neighborhoods"]
  }'
```

The response contains `thread_id`, `user_id`, `travel_plan`, and all
`remembered_preferences` available to that run.

The older endpoint remains compatible:

```bash
curl --noproxy '*' --fail --silent --show-error \
  -X POST http://127.0.0.1:8000/api/v1/agents/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "origin": "Shanghai",
    "destination": "Tokyo",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "budget": "10000.00",
    "currency": "CNY",
    "travelers": 1,
    "preferences": ["photography"]
  }'
```

## Read state, history, and preferences

```bash
curl --noproxy '*' --fail --silent --show-error \
  http://127.0.0.1:8000/api/v1/agents/threads/demo-thread-1/state

curl --noproxy '*' --fail --silent --show-error \
  'http://127.0.0.1:8000/api/v1/agents/threads/demo-thread-1/history?limit=20'

curl --noproxy '*' --fail --silent --show-error \
  http://127.0.0.1:8000/api/v1/users/demo-user/preferences
```

The state view omits runnable config, connections, store objects, and internal task exceptions.
History accepts limits from 1 through 100.

## Prove restart and user isolation

1. Create `demo-thread-1` with the request above.
2. Stop Uvicorn with `Ctrl+C` and wait for graceful shutdown.
3. Start the same Uvicorn command again.
4. Read `demo-thread-1/state`; the completed state should still exist.
5. Create `demo-thread-2` with the same `user_id` and empty `remember_preferences`. It should read
   `quiet neighborhoods`.
6. Create `demo-thread-3` with another `user_id`. It should not see that preference.

This separately proves restart durability, same-user cross-thread memory, and cross-user
isolation.

## Delete exactly one preference

List preferences, copy the intended `preference_id`, then run:

```bash
curl --noproxy '*' --fail --silent --show-error \
  -X DELETE \
  http://127.0.0.1:8000/api/v1/users/demo-user/preferences/PREFERENCE_ID
```

Success is HTTP 204 with no body. A missing item returns `preference_not_found`. The endpoint
never clears the whole namespace.

## Safe error codes

- `persistence_not_initialized`: the application-owned P07 resources are unavailable.
- `checkpoint_unavailable`: invocation, latest state, or history could not use checkpoints.
- `store_unavailable`: preference memory could not be read or written.
- `invalid_thread_id`: the thread ID is empty, too long, or contains unsafe characters.
- `invalid_user_id`: the user ID is empty, too long, or contains unsafe characters.
- `preference_not_found`: that exact item does not exist for that user.

Errors omit raw database messages, connection URIs, passwords, and API keys.

## Tests

Ordinary checks need no Docker integration:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

After Docker and setup are ready, run PostgreSQL integration explicitly:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

When enabled, connection failure is a real failure. The P07 integration test uses unique thread
and user prefixes, closes and reopens official PostgreSQL resources, verifies typed state,
history, preference persistence, and user isolation, then deletes only its own thread and item.

## Stop without deleting data

Stop FastAPI with `Ctrl+C`. Either command below retains named volumes:

```bash
docker compose stop
docker compose down
```

Do not run `docker compose down -v` during ordinary work. `-v` deletes the PostgreSQL, Redis, and
Chroma named volumes, destroying local checkpoints, preferences, and indexed knowledge. Read
`docs/08_INFRASTRUCTURE.md` before any intentional full reset.

## Security and scope limits

P07 is a local development baseline, not production authentication. Anyone who can reach these
endpoints can supply a `user_id`; it only selects a namespace. Do not expose this server to an
untrusted network. P07 adds no LLM, automatic memory extraction, semantic memory, Redis memory,
Chroma memory, MCP, SSE, reviewer loop, frontend, Alembic, or business database tables.
