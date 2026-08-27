# Phase P16 — Web Chat Frontend

## What changed

P15 added the backend conversation: it extracts partial trip requirements, asks a deterministic
follow-up question, persists the safe conversation, and waits for an explicit confirmation. P16
adds the browser interface for that existing behavior. It does not rewrite intake, the graph,
Planner, Reviewer, RAG, MCP, persistence, or SSE.

The complete local path is:

```text
Browser (React SPA)
  -> FastAPI conversation endpoints
  -> existing Qwen intake boundary
  -> explicit fingerprint confirmation
  -> existing LangGraph planning stream
  -> structured TravelPlan rendered by React
```

The browser never calls Qwen or infrastructure services directly.

## Technology choices

The frontend is an independent single-page application in `frontend/`:

- React 19.2 for components and hooks;
- TypeScript 6.0 in strict mode for compile-time checking;
- Vite 8 for the local development server and production bundle;
- Tailwind CSS 4.3 through its official first-party Vite plugin;
- Zod for runtime validation of every HTTP and SSE payload;
- Vitest, React Testing Library, and user-event for offline tests;
- Playwright for mock browser end-to-end tests.

A Vite SPA is enough because FastAPI remains the only backend and the product does not need
server-side rendering. Next.js would add a second server boundary without solving a P16 need.
Redux, React Query, a router, Axios, WebSocket, GraphQL, and a component framework are also omitted;
`useReducer`, small hooks, native `fetch`, and the current one-screen workflow are sufficient.

The version choices follow the current stable releases and compatibility declarations. Vite 8
supports the installed Node 24 runtime. `typescript-eslint` currently declares TypeScript support
below 6.1, so the project deliberately uses TypeScript 6.0 instead of blindly taking TypeScript 7.
See the official [Vite guide](https://vite.dev/guide/),
[React versions](https://react.dev/versions), and
[Tailwind Vite installation](https://tailwindcss.com/docs/installation/using-vite).

## Development proxy and CORS

Vite serves the browser at `http://127.0.0.1:5173` and proxies relative `/api`, `/health`, and
`/ready` requests to `http://127.0.0.1:8000`. FastAPI CORS was not changed. This keeps development
same-origin from the browser's perspective and avoids an unsafe wildcard origin.

`frontend/.env.example` contains only:

```dotenv
VITE_API_BASE_URL=
```

An empty value uses relative URLs and the proxy. Every `VITE_*` value becomes public browser code,
so no Qwen key, database URL, Redis credential, or backend environment value belongs there.

## Local identity and thread identity

There is no authentication in this local demo. On first load, the browser creates a random UUID
with `crypto.randomUUID()` and stores it under `travel-planner:user-id`. This value is a namespace,
not proof of identity.

Each New Trip creates a separate random `thread_id`. The current thread and at most ten recent
thread metadata records are saved locally. Recent metadata contains only:

- `threadId`;
- `createdAt`;
- a display title derived from the backend draft destination.

Local storage never contains complete messages, a TravelPlan, Qwen output, raw SSE, credentials,
or remembered preference payloads. The backend conversation store is the source of truth.

## Reload, New Trip, and Reset

On reload, the app reads only the user/thread pointers and calls `GET /conversation`. The response
restores messages, status, draft, missing fields, and fingerprint. If the conversation reports an
available plan, the app reads the existing safe thread state to restore that structured plan; it
does not execute the graph again. A 404 means this UUID has no conversation yet and produces the
welcome state.

New Trip keeps the local user ID, creates a new thread UUID, and leaves the old thread checkpoint
untouched. When the current draft contains messages, the browser asks before switching.

Reset asks for confirmation and calls the real `POST /conversation/reset` for only the current
user/thread. It clears browser messages, draft display, progress, and final-plan display while
retaining the user identity and long-term preference store.

## Conversation and draft UI

The chat shows only P15's safe user and assistant messages. Example prompts fill the textarea but
do not send automatically. Enter submits; Shift+Enter inserts a line break. Sending and planning
disable the composer, empty content is rejected, and both the HTML and TypeScript boundary enforce
P15's 4,000-character maximum. A failed message remains available for one explicit retry; POST
mutations are never automatically repeated.

Trip Draft displays only the backend's `draft`. It does not parse prose or guess that “Tokyo” is a
destination. Missing and completed fields use both icons and text, so color is not the only signal.
Null fields display `Not set`; dates and currencies use `Intl.DateTimeFormat` and
`Intl.NumberFormat`. Monetary strings are formatted for display, not used for new price math.

When P15 returns `status=awaiting_confirmation` and `can_confirm=true`, the confirmation card is
shown. Nothing auto-confirms. The request sends the current backend `draft_fingerprint`; the
browser never creates it. A 409 stale response triggers `GET /conversation`, shows the latest
draft, and asks the user to review again without automatically retrying confirmation.

“Remember selected preferences” defaults to false. When selected, it sends only preference strings
already present in the current backend draft. It does not remember destination, dates, budget, or
other trip fields.

## POST SSE streaming

The confirmation stream is POST plus a JSON body, so native browser `EventSource` cannot be used.
The app uses `fetch()`, `response.body.getReader()`, `TextDecoder`, and a small incremental parser.

The parser supports:

- arbitrary network byte boundaries;
- UTF-8 characters split across chunks;
- LF and CRLF line endings;
- blank event separators;
- `id`, `event`, and multiple `data` lines;
- final-buffer flush;
- ignored unknown SSE fields;
- `: ping` heartbeat comments.

Heartbeat is transport keepalive only. It is not returned as a business event and does not consume
`event_id` or `sequence`. Each known JSON event passes a strict Zod discriminated union. Unknown
future event names are ignored; a known event with malformed JSON, unexpected fields, a mismatched
event name, or a non-continuous sequence stops the planning UI with a bounded error. The app never
uses `eval`, `Function`, `innerHTML`, or `dangerouslySetInnerHTML`.

The client continues reading through stream EOF after `plan_completed`. This matters because the
FastAPI generator records the planned intake only when execution resumes after yielding the
terminal event. Exactly one `plan_completed` or `error` is accepted; a business event after a
terminal is a protocol error.

## Progress, review, and final plan

Internal graph names are mapped into six user-facing stages: Understanding, Travel knowledge,
Travel search, Drafting, Reviewing, and Finalizing. Flights, hotels, attractions, weather, and
route each have independent pending/running/completed/failed status. Their display never assumes a
completion order and does not claim prices or inventory are live.

`review_completed` shows the round and five public scores. A revise decision and
`revision_started` display “Improving your itinerary” without exposing hidden reasoning, prompts,
state, or chain of thought. A small collapsed developer area lists only public event type names.

`plan_completed.data.travel_plan` becomes the final results page. React renders structured trip,
flight, hotel, daily itinerary, total, backend budget warning, and the latest public review. Raw
Markdown is not injected. Flight and hotel cards say “Demo data”; the page says that options are
deterministic samples rather than live booking inventory. There are no Book, Reserve, or payment
controls.

## Abort, disconnect, retry, and request IDs

Stop calls `AbortController.abort()`. Unmounting, Reset, New Trip, and selecting another thread also
abort the active POST stream. The UI then reads the latest conversation and returns to the backend
status, normally `awaiting_confirmation`; cancellation is not converted into a business error.

An unexpected EOF without a terminal is shown as a disconnected stream. A terminal error offers
one user-controlled Retry Planning action. Retry first uses the latest conversation and therefore
the latest fingerprint. There is no infinite retry. GET may retry once after a transport failure;
message and confirmation POSTs never auto-retry.

Errors show bounded categories such as unavailable conversation service, stale draft, validation,
network, timeout, or planning failure. The UI never prints raw exceptions, request bodies, DSNs,
tokens, or internal objects. When FastAPI supplies `X-Request-ID`, failures may show it as a safe
diagnostic reference.

## Responsive and accessible design

At desktop widths, the layout uses navigation, chat/results, and a draft/progress column. Tablet
uses one main content column with collapsible detail content. Mobile starts with a collapsed Trip
details bar followed by chat, avoiding a draft panel that consumes the first screen. Checks cover
375, 768, 1280, and 1440 pixels without horizontal page overflow.

The UI uses semantic headings, buttons, labels, lists, and descriptions; a polite live region for
new assistant content and aggregated planning progress; `role=alert` for errors; visible keyboard
focus; text/icon status signals; and focus on the final-plan heading after completion. CSS respects
`prefers-reduced-motion`. Dark mode is deliberately deferred so P16 can keep one well-tested visual
system.

## Testing and build

Ordinary frontend checks are offline:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test:run
npm run build
```

The unit/component suite covers API errors, request IDs, conversation controls, draft rendering,
confirmation, preference opt-in, five-way progress, review/revision, final plan, local storage,
abort/resync, and the incremental SSE parser. It uses no backend or model.

Install the browser once, then run the mock browser flow:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

The Playwright test runs desktop and mobile Chromium. It mocks two conversation turns and a full
SSE sequence, asserts the exact fingerprint, and renders the final itinerary without Docker,
network travel data, or Qwen.

A real browser/Qwen E2E is deliberately separate and should be gated by `RUN_UI_E2E=1`, healthy
core infrastructure, and an explicitly configured backend. Run at most one full paid flow and do
not assert exact model prose. P16 does not make it part of ordinary `npm test`.

After starting the real configured backend, the one-desktop-flow command is:

```bash
cd frontend
RUN_UI_E2E=1 npm run test:e2e -- --grep "gated real backend"
```

The mobile project remains skipped under this gate so one command cannot accidentally run the paid
journey twice.

Backend regression remains:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

With local services healthy, the existing explicit integration gate remains:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

## Beginner local startup

Start Docker Desktop first.

Terminal A:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/setup_langgraph_persistence.py
```

Terminal B:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Terminal C:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The status indicator calls only `/health`; it intentionally does not
show PostgreSQL, Redis, or Chroma details to ordinary users. Stop Vite and FastAPI with Control+C.
Use `docker compose stop` to stop containers while retaining named-volume data.

If 5173 is busy on macOS, inspect it with:

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

If FastAPI is unavailable, the page stays rendered, reports Unavailable, and retains textarea
content already typed in the browser. Use the status button or visible retry action after the
backend returns; there is no infinite health polling.

## Current limitations

- Local UUIDs are not authentication or authorization.
- Travel/RAG/provider results remain deterministic demo data, not live inventory.
- There is no booking, payment, deployment, offline PWA, or native mobile app.
- SSE has no Last-Event-ID replay and streams workflow progress, not model tokens.
- Native EventSource cannot represent this POST-body confirmation contract.
- Real Qwen browser E2E is explicitly gated and is not an ordinary test.
