# Phase P12 — SSE streaming and cancellation

This guide explains Phase P12 for someone new to Python and web APIs. P12 does not replace the
travel-planning graph. It lets a client watch one existing graph run as it progresses.

## P11 and P12 are different

P11 put the five deterministic travel tools behind MCP. P12 observes the persistent LangGraph
workflow and sends progress to an HTTP client. Direct and MCP search modes both use the same P12
stream. P12 does not redesign MCP, search, RAG, Planner, or Reviewer.

## What SSE means

Server-Sent Events (SSE) is a long-lived HTTP response. The client sends one request. The server
then sends small text frames one after another over the same response:

```text
event: run_started
data: {"event_id":1,"thread_id":"demo",...}
id: 1

event: node_started
data: {"event_id":2,"thread_id":"demo",...}
id: 2

```

The blank line finishes one frame. FastAPI 0.141.1 writes the legal order `event`, `data`, then
`id`; SSE clients identify fields by name, not position. FastAPI's `ServerSentEvent` performs the
framing and JSON encoding. Quotes, newlines, Chinese text, dates, datetimes, Decimal values, and
Enum values are converted through validated Pydantic models before FastAPI writes the bytes.

## Why SSE instead of WebSocket

P12 only needs one direction after the request starts: server to client. SSE keeps normal HTTP
request validation, status codes, proxy behavior, and command-line testing. WebSocket is useful
for continuous two-way messages, but would add protocol and lifecycle complexity that this phase
does not need.

## Why the endpoint is POST

The endpoint is:

```text
POST /api/v1/agents/threads/{thread_id}/plans/stream
```

It reuses the exact `ThreadPlanRequest` body from the old non-streaming persistent endpoint:

```json
{
  "user_id": "local-stream-user",
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
  "remember_preferences": ["Quiet neighborhoods"]
}
```

A request body this structured does not belong in a GET query string. The browser's built-in
`EventSource` object only opens GET-style streams, so it is not a direct fit for this endpoint. A
future frontend should call `fetch()` with `method: "POST"`, then incrementally read
`response.body` as a `ReadableStream`. P12 deliberately does not add that frontend.

## Business event contract

Every business event is a strict Pydantic model with these fields:

| Field | Meaning |
| --- | --- |
| `event_id` | Same positive integer as `sequence`; used for SSE `id:`. |
| `thread_id` | Validated persistent thread identifier. |
| `event_type` | One allowlisted public event name. |
| `node` | Safe public node name, never a private namespace. |
| `sequence` | Starts at 1 and increases by exactly 1 for business events. |
| `timestamp` | Timezone-aware UTC ISO 8601 datetime. |
| `status` | `started`, `completed`, or `failed`. |
| `message` | Bounded safe human-readable text. |
| `data` | Explicitly constructed JSON-safe whitelist data. |

One connection owns one sequence counter. Heartbeats do not call that counter.

### `run_started`

This is the first business event and appears once. It reports only `backend_mode` and
`persistent=true`; it does not echo the request or private preferences.

### `node_started` and `node_completed`

LangGraph task events use an explicit mapping:

| Internal node | Public node |
| --- | --- |
| `memory_context` | `memory_context` |
| `router` | `router` |
| `retriever` | `advanced_retriever` |
| `prepare_search_tasks` | `search_preparation` |
| `aggregate_search_results` | `search_aggregation` |
| `initialize_review_cycle` | `review_cycle` |
| `planner` | `planner` |
| `reviewer` | `reviewer` |
| `finalize_plan` | `finalize_plan` |

An unknown internal name is ignored. Raw task input, result, task ID, triggers, namespace,
RunnableConfig, and State are never included.

### Search events

Each real P08 `Send` worker produces one `search_started` and one terminal
`search_completed` or `search_failed`. The public categories are `flights`, `hotels`,
`attractions`, `weather`, and `route`.

A successful event exposes only category, `status=ok`, and result count. A failure exposes only
category, a stable error code, and `recoverable`. It never sends provider data, MCP ToolMessage,
request fingerprint, URL, command, exception, or traceback. Completion order is intentionally not
specified because the five workers remain parallel.

### `retrieval_completed`

The P10 update may expose only:

- `returned_parent_count`;
- `query_variant_count`;
- `cache_status`;
- `metadata_filter_applied`;
- `metadata_filter_fallback_used`;
- a safe retrieval error code when degradation occurred.

It does not expose context text, parent IDs, embeddings, cache keys, corpus fingerprint, model
internals, candidates, or raw scores.

### `review_completed` and `revision_started`

`review_completed` is built from a validated `PlanReview`. It contains the actual review round,
decision, four component scores, overall score, issue codes, critique, and suggested changes. The
server does not invent or recompute a score in the streaming layer.

When the real decision is `revise`, the next domain event includes `revision_started`; Planner
then runs again. `accept` does not emit a revision event. `forced_finalize` is a legal successful
result, not an error, and reports `max_review_rounds_reached`.

### `plan_completed`

A successful stream has exactly one `plan_completed`, and it is the final business event. Its
`travel_plan` uses the same `TravelPlan` schema as the old persistent endpoint. The value is
validated with `TravelPlan.model_validate()` before it can cross the SSE boundary. After this
event the generator ends, so no later node event or heartbeat is sent.

### `error`

An error after streaming begins produces exactly one terminal `error` and no `plan_completed`.
It contains only `error_code`, `safe_message`, and `recoverable`. Raw exception text, DSNs,
passwords, tokens, URLs, environment variables, local paths, commands, and traceback are not
serialized. The HTTP status is already 200 because headers were sent; the SSE event carries the
failure.

## Errors before and after streaming starts

FastAPI validates the body before creating the generator. A dependency also validates
`thread_id`, `user_id`, persistence availability, and MCP readiness before SSE headers are
committed. These failures use normal JSON HTTP 4xx/503 responses.

After `run_started`, changing the HTTP status is impossible. Graph, checkpoint, search, or runtime
failures become the terminal SSE `error`. This difference is normal for every streaming protocol.

## Heartbeat and backpressure

`SSE_HEARTBEAT_SECONDS` defaults to 10 seconds and accepts values greater than zero through 14.
During an idle period the application sends:

```text
: ping

```

This is an SSE comment, not a business event. It has no ID, sequence, timestamp, or JSON payload.
FastAPI 0.141.1 also has a fixed 15-second native fallback ping. The application setting stays
below 15 seconds, so the configurable comment normally arrives first without changing FastAPI's
private constant.

The Graph producer writes to an `asyncio.Queue` whose validated `SSE_QUEUE_MAXSIZE` defaults to
64. `await queue.put()` naturally pauses a fast producer when a client is slow; business events
are never randomly dropped. FastAPI adds a final capacity-1 transport buffer around the route.

## Disconnect and cancellation

FastAPI/Starlette cancels the route generator when a browser refreshes, curl is interrupted, the
connection closes, or the application shuts down. The generator's `finally` block cancels the
Graph producer if it is still running and then awaits it. The graph async generator is closed,
and `asyncio.CancelledError` is suppressed only during this expected cleanup. Ordinary exceptions
are converted to the safe terminal error instead of becoming silent producer crashes.

The disconnected client receives no `stream_cancelled`, `error`, or `plan_completed` event. A
bounded queue and a private internal completion sentinel coordinate the two tasks; the sentinel is
never sent over HTTP. Its cleanup insertion is non-blocking and may be omitted when the queue is
already full, because every connected success or failure path exits on its terminal business
event. This prevents a disconnected consumer from leaving the producer blocked on cleanup.

## The Graph executes once

One request calls exactly one:

```python
graph.astream(
    initial_state,
    config=config,
    context=context,
    stream_mode=["tasks", "updates"],
    version="v2",
)
```

`tasks` supplies task/node lifecycle and each parallel search worker. `updates` supplies safe
retrieval, review, revision, and final-plan fields. The service never calls `ainvoke()`.

Normally the `finalize_plan` update contains the final plan. If a completed stream lacks that safe
value **and no error was observed**, the service may call `aget_state(config)` once to read the
same run's saved final checkpoint. It never reads this fallback on a failure path, and it accepts a
fallback plan only when the plan's requirements exactly match the current request. Therefore a
reused thread cannot return an older Tokyo plan for a new Paris request. Reading a checkpoint does
not execute the graph again. If that state is absent, invalid, or belongs to a different request,
the stream ends with `stream_invalid_final_state`.

## P08 parallel search is unchanged

P12 does not call SearchBackend itself. The existing conditional edge still dispatches five
`Send("search_worker", ...)` tasks. The stream only observes their task events. Clients must not
assume which search finishes first. Different thread streams may run concurrently.

P12 adds no distributed or business-level same-thread lock. Use one active planning mutation
request or stream per thread. Concurrent mutations on the same thread have the same checkpoint
limitations as the old persistent endpoint.

## Direct and MCP modes

Direct remains the default and uses deterministic P03 providers. In MCP mode, start the local HTTP
MCP Server first, then start FastAPI with `TRAVEL_SEARCH_BACKEND_MODE=mcp`. If MCP discovery is
already known to be unavailable, the streaming endpoint returns JSON HTTP 503 before opening SSE.
It never silently falls back to direct.

## Command-line example

```bash
curl --noproxy '*' -N \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/p12-stream-request.json \
  'http://127.0.0.1:8000/api/v1/agents/threads/my-stream-thread/plans/stream'
```

`-N` disables curl's output buffering. Put the exact request JSON shown earlier into the temporary
file; do not put API keys or passwords there.

## Current limitations

- There is no real LLM, Qwen, OpenAI, Anthropic, or token-level LLM streaming.
- All travel providers and MCP tools still return deterministic invented mock data.
- The RAG corpus is a small static local demo, not current travel information.
- There is no live flight/hotel inventory, real-time weather/map data, booking, or payment.
- There is no authentication, public TLS guidance, frontend, Prometheus, Grafana, or new LangSmith
  integration.
- There is no SSE replay and no `Last-Event-ID` resume.
- P12 does not guarantee business serialization for concurrent mutation requests on one thread.
- A successful local test does not imply production readiness or exactly-once distributed
  execution.

## How to decide that P12 works

Run the normal quality checks and explicit integration test described in `AGENTS.md`. A real curl
stream should have monotonic IDs, `run_started` first, all five search categories, retrieval and
review progress, and exactly one terminal event. After success, the thread state endpoint should
return a complete validated TravelPlan. Interrupting curl should leave no Uvicorn, MCP, or pending
producer process after the application is stopped.
