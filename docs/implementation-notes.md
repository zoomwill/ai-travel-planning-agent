# Implementation Notes

Record deviations from source pseudocode and important engineering decisions here.

## Template

### Date — Topic

- Source intent:
- Implemented approach:
- Why:
- Verification:
- Remaining limitation:

### 2026-08-07 — Phase P01 container versions and health checks

- Source intent: Run PostgreSQL, Redis, and Chroma locally with persistent data and independently
  verifiable service health.
- Implemented approach: Pin `postgres:16.14-alpine`, `redis:7.4.9-alpine`, and
  `chromadb/chroma:1.5.9`; retain named volumes; bind development ports to `127.0.0.1`; use
  `pg_isready` and `redis-cli ping` as container healthchecks; call Chroma's official
  `/api/v2/healthcheck` endpoint from the host-side standard-library script.
- Why: Mutable major-only or `latest` tags can change without a repository change. Chroma does
  not guarantee that its runtime image contains `curl`, so host-side Python avoids relying on an
  undocumented container utility.
- Verification: The initial Docker Hub connection timeout was resolved by configuring Docker
  Desktop to use the local system proxy; no proxy address or credentials are stored in the
  repository. `docker compose config --quiet` passes. `docker compose ps` shows PostgreSQL and
  Redis healthy and Chroma running. The explicit infrastructure script reports PostgreSQL
  accepting connections, Redis `PONG`, and Chroma HTTP 200 with its executor and log client
  ready. All three named volumes exist. The focused pure-logic suite passed 10 tests; the final
  project suite passed 11 tests; Ruff formatting, Ruff linting, and mypy all pass.
- Remaining limitation: Image tags pin versions but not immutable image digests. Chroma has no
  container-level healthcheck, so Compose waits for its container to run and the explicit script
  verifies HTTP readiness afterward.

### 2026-08-07 — Phase P02 async infrastructure clients and lifespan

- Source intent: Give the FastAPI application typed PostgreSQL, Redis, and Chroma clients with
  safe startup, readiness checks, dependency injection, and shutdown cleanup.
- Implemented approach: Use SQLAlchemy 2.0's `create_async_engine()` and official `asyncio` extra
  with the Psycopg 3 `postgresql+psycopg` dialect and `pool_pre_ping=True`; use
  `redis.asyncio.Redis` with finite socket timeouts and public `aclose()`; use Chroma's official
  `AsyncHttpClient` and v2 heartbeat behind a lazy, lock-protected provider. A dataclass resource
  container is created by FastAPI's async lifespan, stored on `app.state`, and read through
  request dependencies. Readiness probes all three services concurrently with independent
  deadlines and returns only `ok` or `error`.
- Why: The architecture screenshots are pseudocode and do not define current client lifecycle
  APIs. FastAPI's supported lifespan API replaces deprecated startup/shutdown event decorators.
  Structured SQLAlchemy URLs safely handle password punctuation. Chroma's async factory performs
  tenant/database network validation, so running it during application startup would make
  liveness unavailable during a Chroma outage.
- Verification: Compose configuration parsing, final container status, and the independent P01
  infrastructure checker all pass. The first explicit integration run exposed that plain
  SQLAlchemy did not include `greenlet` for async engine disposal; changing the dependency to
  `sqlalchemy[asyncio]` fixed the shutdown failure. The rerun passed one real Docker integration
  test. In a live Uvicorn process, liveness returned HTTP 200 and readiness returned HTTP 200 with
  all services `ok`; after intentionally stopping only Redis, liveness remained HTTP 200 and
  readiness returned HTTP 503 with PostgreSQL and Chroma still `ok` and Redis `error`; after
  restarting the same Redis container, readiness returned HTTP 200 again. Uvicorn then completed
  graceful application shutdown with exit code 0 and released port 8000. The ordinary pytest
  suite passed 27 tests with one explicitly skipped Docker integration test. Final Ruff lint
  passed, Ruff confirmed all 66 files were formatted, and mypy found no issues in 25 application
  source files.
- Remaining limitation: Chroma 1.5.9's public `AsyncClientAPI` has no `close()`, `aclose()`, or
  `stop()` method. Its internal HTTP component closes sessions when its private system stops, but
  the application does not depend on private internals. The provider releases its reference at
  shutdown. Also, Chroma indirectly permits NumPy 2.5, which requires Python 3.12; NumPy is
  constrained to the current 2.4 maintenance line so this project retains its declared Python
  3.11 compatibility. The current FastAPI/Starlette `TestClient` emits one upstream deprecation
  warning about its httpx compatibility layer.

### 2026-08-08 — Phase P03 domain models and deterministic mock providers

- Source intent: Establish shared models for trip requirements, travel provider results, final
  plans, review scores, and safe tool errors; provide local mock travel services that return the
  same result for the same input.
- Implemented approach: Use Pydantic v2 `BaseModel`, `Field` constraints, and after-mode
  `model_validator` methods. Represent dates and times with standard-library types, money with
  `Decimal`, and supported currency/transport values with `StrEnum`. Keep models in `app/domain`
  and business behavior in `app/services/mock_providers`. Providers use immutable templates and
  stable calculations derived only from city text and trip dates. Curated Tokyo and Shanghai
  examples are supplemented by deterministic generic city fallbacks.
- Why: Typed models give later Agents one validated communication contract. `Decimal` avoids
  binary floating-point money artifacts. The source's attraction, route, and daily-itinerary
  sketches contain monetary fields without currency, so those models also carry `currency` to
  keep each amount meaningful. Pydantic 2.13 cannot resolve an annotation written as `date: date`
  because the field name shadows the imported type in the class body; importing the type as
  `Date` preserves the required public field name while using the current supported API.
- Verification: The focused domain and service suite passed 48 tests. Project-wide Ruff lint
  passed, Ruff confirmed all 81 Python files were formatted, mypy found no issues in 35
  application source files, and the ordinary project suite passed 75 tests with one explicitly
  skipped Docker integration test. The existing FastAPI/Starlette TestClient compatibility
  warning remains unchanged from P02.
- Remaining limitation: Every provider result is invented test data, not live availability or a
  measured forecast. Fixed currency factors exist only to create internally consistent examples
  and are not exchange rates. Flight datetimes are simple local mock values without IANA timezone
  identifiers. Curated city templates are intentionally limited, with generic fallbacks for other
  valid cities. P03 does not choose options or assemble a plan; that belongs to P04.

### 2026-08-08 — Phase P04 deterministic planning service and HTTP API

- Source intent: Build a “Single-Agent Planning MVP” that turns requirements plus flight, hotel,
  attraction, weather, and route results into a complete structured plan and a readable Markdown
  representation.
- Implemented approach: Use an ordinary synchronous `planning_service` with an immutable bundle
  of typed provider callables. It selects the first flight and highest-rated hotel, builds one day
  for each inclusive trip date, cycles deterministic attractions, attaches matching weather, and
  returns a Pydantic `TravelPlan`. FastAPI exposes that service at `POST /api/v1/plans/mock` with a
  typed request and response. `TravelPlan` gained backward-compatible `budget_warning` and
  `markdown` fields.
- Why: P04 explicitly forbids Agent, LangGraph, LLM, RAG, MCP, and streaming work. A service
  boundary preserves the source's planning behavior and can later be called by an Agent without
  coupling business rules to HTTP. Current FastAPI request-body and `response_model` APIs use
  Pydantic models directly, so invalid request data is handled as HTTP 422. The route translates a
  known planning failure into a safe HTTP 503 instead of leaking a chained exception.
- Verification: Focused service and API tests passed 16 tests. Final Ruff lint and format checks
  passed, mypy found no issues in 37 application source files, and the full ordinary suite passed
  91 tests with one explicitly skipped Docker integration test. A live Uvicorn request for a
  five-day Shanghai-to-Tokyo trip returned HTTP 200 with five itinerary entries, a total of
  `6300.00 CNY`, no budget warning for the `10000.00 CNY` budget, and nonempty Markdown. Because
  this development computer uses a system proxy, the successful localhost curl explicitly used
  `--noproxy '*'`; the first curl without that flag never reached Uvicorn and was terminated.
  Uvicorn then completed graceful application shutdown with exit code 0 and no shutdown warning.
- Remaining limitation: The P04 formula intentionally uses the selected flight price once, hotel
  price multiplied by inclusive trip days, and per-traveler attraction admissions as daily
  activity cost. It does not add the mock route estimate, taxes, meals, or other spending. The
  route provider currently reports only CNY, so keeping it descriptive also avoids mixing
  currencies. Preferences are carried in the response but do not alter ranking yet. All provider
  data remains invented and deterministic; no live availability or production readiness is
  claimed.

### 2026-08-09 — Phase P05 deterministic LangGraph Agent runtime

- Source intent: Introduce typed LangGraph orchestration around travel planning. The repository's
  earlier P05 prompt described a development checkpointer and explicitly deferred Router work,
  while the current user instruction instead requires a deterministic Router followed by Planner
  and does not authorize persistence or memory.
- Implemented approach: Declare `langgraph>=1.0,<2.0` and `langchain-core>=1.0,<2.0`, resolved to
  LangGraph 1.2.10 and langchain-core 1.5.3 for this lockfile. Define a five-field
  `TravelPlanState` `TypedDict`, deterministic Router and Planner node functions, and compile
  `START → router → planner → END` with the current `StateGraph` Graph API. The Planner delegates
  all plan creation to P04's `create_mock_travel_plan()`. FastAPI invokes the compiled graph at
  `POST /api/v1/agents/plans` and returns the existing Pydantic `TravelPlan` response.
- Why: The current user request takes precedence over the older phase prompt, so P05 now proves
  the requested Router-to-Planner runtime but deliberately omits checkpointer persistence. The
  official LangGraph v1 documentation supports `TypedDict` state, partial node updates,
  `StateGraph`, `START`, `END`, `compile()`, and synchronous `invoke()`. LangGraph's generic
  `Runnable.invoke()` surface is typed as `Any`, so the API boundary casts its known compiled-graph
  result back to `TravelPlanState`; FastAPI still validates the final declared response model.
- Verification: Focused graph and Agent API tests passed 13 tests. Final Ruff lint and format
  checks passed, mypy found no issues in 43 application source files, and the complete ordinary
  suite passed 104 tests with one explicitly skipped Docker integration test. A live Uvicorn POST
  to `/api/v1/agents/plans` returned HTTP 200 with a five-day Tokyo `TravelPlan`, a total of
  `6300.00 CNY`, and nonempty Markdown. Uvicorn then completed graceful application shutdown with
  exit code 0.
- Remaining limitation: Intent classification is fixed keyword matching, the graph has no
  conditional branches, and there is no LLM, prompt, checkpointer, thread isolation, persistence,
  resume, memory, RAG, MCP, reviewer, SSE, or real travel API. `langchain-core` is a declared
  runtime foundation but no model or prompt component is used in this phase.

### 2026-08-09 — Phase P06 local RAG and Retriever Agent

- Source intent: Add a deterministic RAG pipeline and insert a Retriever Agent between Router and
  Planner. This user-directed P06 moves basic RAG earlier than the repository plan, where P06 was
  requirement collection and the fuller hybrid RAG design was P09.
- Implemented approach: Load four local Markdown guides as LangChain `Document` objects, split
  them into fixed overlapping chunks, create normalized 128-dimensional hashed bag-of-words
  vectors, and upsert deterministic chunk IDs into the existing Chroma `travel_knowledge`
  collection. The graph is now `START → router → retriever → planner → END`. The graph factory
  accepts a retrieval callable so tests use fakes while the application uses Chroma. The Planner
  continues to call P04 unchanged and only appends retrieved context to its Markdown output.
- Why: The current user instruction takes precedence over the older phase sequence. Chroma 1.5.9's
  current official Python API supports `HttpClient`, `get_or_create_collection`, `upsert`, and
  `query` with caller-provided embeddings. `upsert` makes the explicit indexing script safely
  repeatable without reset or collection deletion. No sentence-transformers dependency was added:
  installing its Python package would not bundle chosen model weights, and downloading weights
  would violate the offline, reproducible validation goal. An embedding Protocol leaves room for
  a future local trained model.
- Verification: Pure RAG, graph, and Agent API focused tests passed 30 tests without network
  access. The existing infrastructure checker reported PostgreSQL accepting connections, Redis
  `PONG`, and Chroma HTTP 200 ready. The explicit indexer upserted nine chunks from four Markdown
  files; running it a second time left the real collection count at nine, proving deterministic
  IDs and repeatable upsert behavior. A real `Tokyo photography trip` search returned four
  chunks, and the real graph reached Planner with four context entries, a `6300.00 CNY` plan, and
  a retrieved-knowledge Markdown section. A live Agent API request returned HTTP 200 with the same
  plan and knowledge section, after which Uvicorn shut down cleanly with exit code 0. Final Ruff
  lint and format checks passed, mypy found no issues in 49 application files, and the complete
  ordinary suite passed 121 tests with one explicitly skipped Docker integration test.
- Remaining limitation: Hash vectors provide lexical similarity rather than strong semantic
  retrieval. This phase does not implement multi-query expansion, BM25, RRF, reranking,
  parent-document mapping, or Redis caching from the full source design. Chroma's official sync
  client sets its internal httpx timeout to `None`; the adapter adds a caller-visible thread
  deadline, but Python cannot forcibly stop a client call already running in that background
  thread. Retrieved text is visible in Markdown but does not change P04's structured itinerary.
