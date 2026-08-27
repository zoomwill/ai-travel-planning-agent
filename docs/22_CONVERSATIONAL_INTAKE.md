# Phase P15 — Conversational Intake and Explicit Confirmation

## Beginner picture

P14 can reason about a **complete** JSON trip request. P15 adds a small conversation in front of
that workflow:

```text
current user message
  → Qwen extracts one strict patch
  → Python merges and validates the draft
  → Python asks a fixed clarification question
  → user explicitly confirms the current SHA-256 fingerprint
  → the existing P07–P14 planning graph runs once
```

The old complete-JSON endpoints remain available. P15 does not place incomplete requirements in
`TravelPlanState`, does not alter the planning graph, and does not let Qwen decide consent.

## Models and patch semantics

`PartialTripRequirements` is used only while collecting a draft. The unchanged
`TripRequirements` still protects the planning boundary. The partial model adds
`duration_days`; its fields may be absent until the conversation supplies them.

`TripRequirementPatch` changes only fields mentioned in the current turn. For example, “Actually,
Paris” overwrites `destination` but preserves dates and budget. Preferences have separate
`preferences_add` and `preferences_remove` operations. `clear_fields` is the only way to clear a
value; `null` and magic empty strings are rejected. Preference comparison is case-insensitive and
deduplicated while preserving readable text.

Required fields are computed by inspecting the real Pydantic `TripRequirements` fields. In the
current domain model, origin, destination, start date, end date, budget, and travelers are required.
`currency` has a domain default of `CNY`, and preferences may be empty. Qwen never decides this
list.

Trip dates are inclusive. A start date plus five days produces an end date four calendar days
later; an end date plus five days derives the start in the opposite direction. One day means the
same start and end date. Intake permits 1–366 days to match the bounded P14 structured planning
models. An exact month without a day remains missing and causes a clarification question rather
than silently becoming the first of that month. Qwen receives the server's current UTC date for
relative-date interpretation, but all resulting values are validated by Python.

## Conversation lifecycle

Statuses are:

- `collecting`: required or valid fields are still missing.
- `awaiting_confirmation`: the unchanged domain model accepts the complete draft.
- `planning`: an explicit confirmation is currently using the existing planning workflow.
- `planned`: planning completed and the existing graph checkpoint contains the plan.

Clarification text comes from deterministic templates and asks at most two fields in this order:
origin, destination, dates, budget, and travelers as determined by the real model-field order.
When complete, the response summarizes origin, destination, dates, travelers, budget, currency,
and current-trip preferences. It still does not run planning.

Every draft receives a SHA-256 fingerprint over canonical effective JSON. A correction changes the
fingerprint. Confirmation with an older value returns HTTP 409 and does not invoke LangGraph.
Python's randomized `hash()` and timestamps are not part of the fingerprint.

## Endpoints

All endpoints are local-development APIs without authentication. `user_id` selects a Store
namespace; it is not proof of identity.

### Add one message

```http
POST /api/v1/agents/threads/{thread_id}/conversation/messages
Content-Type: application/json

{
  "user_id": "local-user",
  "message": "From Cleveland to Tokyo on 2027-10-12 for five days.",
  "start_new_trip": false
}
```

`message` is 1–4000 characters. `start_new_trip=true` explicitly resets this user's intake key
before processing the current message. Qwen is never allowed to infer that a message begins a new
trip.

The strict response contains only `thread_id`, `user_id`, status, deterministic assistant text,
partial draft, missing/invalid field enums, `can_confirm`, fingerprint, bounded redacted message
history, turn count, version, and `plan_available`. It never returns the prompt, completion, SDK
object, exception, Store metadata, graph State, token, or DSN.

### Read or reset

```http
GET /api/v1/agents/threads/{thread_id}/conversation?user_id=local-user
POST /api/v1/agents/threads/{thread_id}/conversation/reset
Content-Type: application/json

{"user_id":"local-user"}
```

A missing conversation returns 404. Reset writes a new empty intake for exactly this user/thread.
It does not remove another user, another thread, long-term preferences, planning checkpoints, or
database tables. After a planned trip, another message returns 409 until the caller uses reset or
`start_new_trip=true`.

### Confirm once, without streaming

```http
POST /api/v1/agents/threads/{thread_id}/conversation/confirm
Content-Type: application/json

{
  "user_id": "local-user",
  "draft_fingerprint": "copy-the-current-64-character-value",
  "remember_preferences": ["quiet neighborhoods"]
}
```

This returns the same `ThreadPlanResponse` as the existing persistent `/plans` endpoint. Only the
explicit `remember_preferences` list is sent to P07 long-term memory. Preferences extracted into
the current trip are never silently remembered.

### Confirm with P12 workflow progress

```bash
curl --noproxy '*' -N \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "user_id":"local-user",
    "draft_fingerprint":"copy-the-current-64-character-value",
    "remember_preferences":[]
  }' \
  'http://127.0.0.1:8000/api/v1/agents/threads/local-chat/conversation/confirm/stream'
```

This is the existing P12 `TravelPlanStream`: one `graph.astream()` call, the same search/retrieval/
review events, exactly one final `plan_completed` on success, or exactly one final `error` on graph
failure. `: ping` is a transport comment and consumes no event ID. It is workflow progress, not LLM
token streaming. Browser `EventSource` cannot send this POST JSON body; a frontend must use `fetch`
streaming or an equivalent POST-capable client. Last-Event-ID replay is not supported.

If the planning graph fails, or the client disconnects before completion, the draft is retained and
returns to `awaiting_confirmation`. A successful conversation stores only `planned_at` and
`plan_available=true`; it does not duplicate the full `TravelPlan`, which remains in the graph
checkpoint.

## Qwen boundary and cost

Conversational semantic extraction requires configured Qwen mode and the one application-owned
`AsyncOpenAI` client created for P14. There is no second network client or retry layer. The adapter
continues to use bounded application retries, SDK retries disabled, timeout, JSON object mode,
duplicate-key rejection, NaN/infinity rejection, strict numeric fields, unknown-field rejection,
Pydantic validation, real usage counters only, and cancellation propagation.

Only the current structured draft, current redacted message, and current UTC date are sent. The
entire message history is not sent, so prompt size and attack surface remain bounded. Delimiter text
inside the message is JSON-escaped. The system contract permits fact extraction only—no planning,
candidate selection, tools, memory, confirmation, hidden reasoning, or secret output.

Credential-shaped values such as bearer tokens, `sk-...` strings, PostgreSQL/Redis DSNs, cookies,
and obvious key/password assignments are redacted before prompt forwarding and before conversation
history persistence. Logs contain only request ID, pseudonymous user/thread references, bounded
outcome, turn count, and missing-field count—not messages, drafts, preferences, prompts, or
completions.

When the default `AGENT_REASONING_MODE=deterministic` has no provider, conversational messages
return safe HTTP 503 code `conversational_intake_requires_llm`. All older deterministic complete-
JSON endpoints continue to work. Ordinary pytest injects a scripted fake and never contacts Qwen.

## Persistence, restart, isolation, and concurrency

Conversation JSON is stored in the existing PostgreSQL LangGraph Store under namespace
`(user_id, "trip_intake")` and key `thread_id`. This needs no new table or migration beyond the
existing Store setup. It deliberately does not share the planning checkpointer namespace, so a
partial form cannot pollute `TravelPlanState`. Closing and reopening FastAPI restores the draft,
bounded 30-message history, status, turn count, fingerprint, and version. The namespace prevents
the same thread ID under another user ID from reading it.

P15 increments `version` on each mutation and uses the fingerprint for stale confirmation, but the
current Store API does not provide a compare-and-swap write. There is no Redis distributed lock.
Callers must serialize mutations for the same user/thread; simultaneous messages or confirmations
are an explicitly documented local-development limitation.

## Metrics and dashboard

Prometheus adds:

- `travel_planner_intake_turns_total{status}`
- `travel_planner_intake_turn_duration_seconds{status}`
- `travel_planner_intake_confirmations_total{status}`
- `travel_planner_intake_clarifications_total{field}`

Both `status` and `field` use fixed allowlists. Qwen calls use the existing LLM metrics with
`role="intake"`; no user, thread, message, destination, or preference becomes a label. Grafana adds
four panels to the existing 24 without changing them.

## Verification

Offline checks—no Docker, network, MCP server, or Qwen usage:

```bash
uv run pytest tests/intake -q
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

Real PostgreSQL restart recovery, still using fake intake extraction:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest tests/integration/test_intake_integration.py -vv
```

The paid test is separately gated and performs one complete real conversation + confirmation
stream. Never run it merely to run the ordinary integration suite:

```bash
RUN_LLM_INTEGRATION_TESTS=1 uv run pytest tests/integration/test_qwen_integration.py -vv
```

## Current limitations and completion boundary

P15 has no frontend, authentication, TLS, distributed mutation lock, natural-language confirmation,
replayable SSE, token streaming, live flight/hotel/weather/map inventory, booking, payment, or
production readiness. RAG content is local demo material and MCP travel providers are deterministic
mocks. Relative dates have an explicit server-date boundary but ambiguous calendar language still
requires clarification. Completion means a recoverable multi-turn draft, corrections/clears,
deterministic validation, stale-confirmation protection, explicit consent, and reuse of the single
existing planning/SSE execution path—not autonomous booking or P16 work.
