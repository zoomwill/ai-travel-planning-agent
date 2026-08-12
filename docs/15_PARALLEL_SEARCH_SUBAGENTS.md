# P08 — Parallel Travel Search Subagents

P08 changes how the deterministic Agent obtains travel data. P07 made state durable; P08 fans one
request out to five independent search workers and combines their results before planning. It
still uses local mock providers and does not call an LLM or real travel API.

```text
START
  -> Memory Context
  -> Router
  -> Retriever
  -> Prepare Search Tasks
  -> Send x 5
       |-- flights
       |-- hotels
       |-- attractions
       |-- weather
       `-- route
  -> Aggregate Search Results
  -> Planner
  -> END
```

## 20 beginner concepts

1. **P07 versus P08:** P07 answers “where is graph state saved?” P08 answers “how are five
   independent searches scheduled and combined?” PostgreSQL persistence remains active.
2. **Fan-out** means one graph step creates several independent next tasks. Prepare creates five
   tasks, and the conditional edge returns five `Send` objects.
3. **Fan-in** means the five branches meet again. `aggregate_search_results` runs after every
   `search_worker` instance in that super-step finishes.
4. A **Subagent** here is one specialized execution of the generic worker. There is a flight
   subagent, hotel subagent, attraction subagent, weather subagent, and route subagent. No LLM is
   involved.
5. The five queries can run concurrently because none needs another query's output. Every branch
   receives the same request plus its own task.
6. **Send** is LangGraph's official dynamic routing packet. `Send("search_worker", payload)` starts
   one worker with a payload that can differ from the main State.
7. **Map-reduce** means mapping five tasks to worker executions, then reducing their updates into
   stable result and error lists.
8. A **reducer** tells LangGraph how multiple writes to one State field are combined. Without one,
   concurrent workers writing `search_results` would overwrite one another or raise an invalid
   update.
9. The default State behavior is overwrite. It is correct for a single-writer field but unsafe for
   a list written by five parallel workers.
10. P08's custom reducers deduplicate by deterministic `task_id`, sort by the fixed five-kind
    order, and choose duplicate values through canonical JSON. Completion order and retry order do
    not change the final list.
11. **Overwrite** deliberately bypasses a reducer. Prepare wraps empty results, errors, summary,
    and the new task list in `Overwrite`, so a second request on the same persistent thread cannot
    merge with the first request.
12. Planner must not repeat providers because every worker has already queried one provider. It
    validates JSON data back into domain models and calls a pure combination function.
13. **Search Backend** is an injectable Protocol with five async methods. The default backend uses
    `asyncio.to_thread` to adapt the existing synchronous P03 mock providers without copying their
    data or blocking the event-loop thread.
14. **Critical failures** are missing flights or hotels. Planner cannot create an honest plan
    without them, so State keeps all successful sibling results and the API returns a sanitized
    HTTP 503.
15. **Non-critical failures** are missing attractions, weather, or route. Planner creates a
    **degraded plan** that explicitly says which information is unavailable and never invents a
    successful provider result.
16. Real concurrency is proved with a test-only barrier backend. Each method waits on one Event;
    the test releases it only after all five methods have entered. Sequential execution could
    never reach that release condition. The timeout only prevents a hung test and is not a
    performance benchmark.
17. The P07 checkpointer saves P08's Prepare super-step, parallel search super-step, aggregate
    super-step, and final plan. History checkpoint count is intentionally not fixed because graph
    structure can add valid super-steps.
18. The thread state endpoint shows only `search_summary`, `search_result_count`, and
    `tool_error_count`. It omits Send payloads, backend objects, provider exceptions, tracebacks,
    connections, and serializer internals.
19. Every search structure stored in State is JSON-safe. Domain models use
    `model_dump(mode="json")` before State writes and `model_validate()` at the Planner boundary.
20. P08 is complete only when ordinary tests work without Docker, the barrier proves fan-out,
    PostgreSQL strict round-trip succeeds, real HTTP shows five statuses, and a second request on
    one thread contains only the new request's search data.

## Search data structures

`SearchKind` fixes the five values and their display/reducer order:

```text
flights -> hotels -> attractions -> weather -> route
```

`SearchTask` contains only:

- `task_id`
- `kind`
- `request_fingerprint`
- `origin`
- `destination`

The request fingerprint is SHA-256 over canonical JSON for every validated requirement field.
The task ID is another deterministic SHA-256 derived from that fingerprint plus one search kind.
The same request creates the same IDs; a changed date, destination, budget, traveler count,
currency, or preference changes the fingerprint.

`SearchResultEnvelope` contains task identity, kind, `status="ok"`, and a list of JSON objects.
Route also uses a one-item list, so the aggregator can count every kind consistently.

`SearchErrorEnvelope` contains a stable error type, a safe fixed message, and whether retry could
help. It never stores an exception, traceback, provider object, DSN, or password.

## Planner and P04 compatibility

`create_mock_travel_plan()` remains the P04 entry point. It calls the five mock providers in the
old sequential style and passes their results to `assemble_travel_plan_from_results()`.

The P08 Planner calls only `assemble_travel_plan_from_results()`. Therefore selection, itinerary,
cost, budget warning, retrieved knowledge, remembered preferences, and degraded notices have one
implementation rather than two competing Planner implementations.

For independent fan-out, both paths now obtain the route for the trip's validated origin and
destination. The old service previously waited for hotel and attraction selection and requested a
hotel-to-first-attraction route. The route remains descriptive and is not added to the price.

## Search summary

A successful five-day Tokyo request currently produces counts based on existing P03 mocks:

```json
{
  "flights": {"status": "ok", "count": 2},
  "hotels": {"status": "ok", "count": 2},
  "attractions": {"status": "ok", "count": 3},
  "weather": {"status": "ok", "count": 5},
  "route": {"status": "ok", "count": 1}
}
```

Counts describe invented deterministic test data, not live availability.

## Run locally

Start Docker Desktop, then run:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/check_infra.py
uv run python scripts/setup_langgraph_persistence.py
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use the persistent plan example from `docs/14_PERSISTENCE_AND_MEMORY.md`. The response now also
contains `search_summary` and `tool_errors`.

Inspect safe state and bounded history:

```bash
curl --noproxy '*' --fail-with-body --silent --show-error \
  http://127.0.0.1:8000/api/v1/agents/threads/THREAD_ID/state

curl --noproxy '*' --fail-with-body --silent --show-error \
  'http://127.0.0.1:8000/api/v1/agents/threads/THREAD_ID/history?limit=30'
```

## Run checks

Ordinary checks use in-memory persistence and fake backends:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

After Docker is ready, explicitly run PostgreSQL integration:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

The integration test uses unique UUID-prefixed threads and users. It removes only those exact
test threads and its one preference item. It never drops, truncates, resets, flushes, or deletes a
named volume.

## Current limits

- There is no LLM, reviewer loop, reflection, SSE, MCP, authentication, frontend, or real provider.
- `asyncio.to_thread` keeps synchronous providers off the event-loop thread; it does not make a
  slow blocking function cancellable after that thread has started.
- Error handling is deterministic and safe but has no automatic retry policy yet.
- No latency or performance improvement was measured. The barrier proves concurrency structure,
  not speed.
- P08 does not change the P06 RAG algorithm or P07 preference-memory policy.
