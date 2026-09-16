# Implementation Notes

Record deviations from source pseudocode and important engineering decisions here.

Entries below preserve the state at each engineering milestone, not today's deployment status.
For AI Travel Planning Agent's completed P00–P19 implementation, owner-reported P19 publication
and separate verification boundaries, see [P19 acceptance](P19_ACCEPTANCE_REPORT.md).

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

### 2026-08-11 — Phase P07 durable checkpoints and explicit preference memory

- Source intent: The repository's original P07 prompt describes parallel search subagents, while
  the current user-directed P07 explicitly moves durable LangGraph PostgreSQL persistence and
  long-term preference memory into this phase.
- Implemented approach: Add the official `langgraph-checkpoint-postgres` package, resolved to
  3.1.2, and use its async context-managed `AsyncPostgresSaver` and `AsyncPostgresStore`. FastAPI's
  existing lifespan now owns the saver, store, and a graph compiled with both. The graph passes
  `thread_id` only in RunnableConfig and passes `user_id` plus explicitly approved preference
  values in a typed runtime context. Preference records use namespace
  `(user_id, "travel_preferences")`, a deterministic hash ID, JSON-safe values, and duplicate
  upsert. The graph is `START → Memory Context → Router → Retriever → Planner → END`; P04 planning
  and P06 retrieval remain delegated to their existing implementations.
- Why: The current instruction takes precedence over the earlier phase ordering. Current official
  LangGraph APIs compile `StateGraph` with a checkpointer and store, inject typed context through
  `Runtime`, and require `configurable.thread_id` for checkpoints. The PostgreSQL connector expects
  a `postgresql://` URI rather than SQLAlchemy's `postgresql+psycopg://` dialect URL, so `Settings`
  uses SQLAlchemy's structured URL builder for safe component encoding and wraps the rendered URI
  in `SecretStr`. Local development selects `sslmode=disable`; deployments must choose an
  appropriate verified TLS mode. Strict MessagePack is enabled before LangGraph import, graph
  schemas derive the deserialization allowlist, and the saver explicitly sets
  `pickle_fallback=False`.
- Verification: Compose configuration parsing passed; PostgreSQL reported accepting connections,
  Redis returned `PONG`, and Chroma returned HTTP 200 ready. The explicit saver/store setup script
  passed twice, demonstrating idempotent official migrations. All focused offline P07 suites
  passed. Final Ruff lint passed, Ruff confirmed all 134 Python files were formatted, mypy found
  no issues in 56 application files, and the ordinary suite passed 153 tests with two explicitly
  skipped integration tests. Enabling integration ran two tests successfully: readiness plus a
  strict typed PostgreSQL checkpoint/store close-and-reopen round trip with isolated user data and
  exact test-data cleanup. In live Uvicorn, a plan wrote six checkpoints; state, history, and the
  explicit preference API returned HTTP 200 without auto-saving the current `photography`
  requirement. After graceful shutdown and a new server process, the old state remained complete,
  a second thread for the same user recalled `quiet neighborhoods`, another user saw no memory,
  and the legacy Agent endpoint still returned its original direct `TravelPlan` shape. Both server
  processes shut down cleanly with exit code 0, and the live test preference and three exact test
  threads were removed afterward.
- Remaining limitation: This is local development identity routing, not authentication or
  authorization. Preference categories use simple deterministic keywords, not LLM extraction or
  semantic memory. The old non-thread Agent endpoint remains stateless and does not save memory.
  P07 adds no parallel subagents, reviewer loop, SSE, MCP, real travel provider, frontend, Alembic,
  Redis memory, or Chroma memory.

### 2026-08-12 — Phase P08 parallel travel search subagents

- Source intent: The source architecture calls for independent flight, hotel, attraction,
  weather, and map/route subagents with reducer-safe parallel writes. The repository's original
  phase plan calls that work P07 and reserves P08 for a reviewer loop; the current user instruction
  treats durable persistence as completed P07 and explicitly assigns parallel search to P08.
- Implemented approach: Use LangGraph 1.2.10's current Graph API. Prepare creates five JSON-safe
  deterministic tasks. A conditional edge returns five `Send("search_worker", payload)` packets;
  the generic async worker uses an injected `SearchBackend` and writes only result or safe error
  envelopes. Custom pure reducers deduplicate by task ID, choose unexpected duplicate values by
  canonical JSON, and sort by fixed kind order. Prepare uses `Overwrite` once per reducer channel
  to reset tasks, results, errors, and summary before a new run on a reused thread. One fan-in
  aggregator creates stable counts before Planner.
- Why: Official LangGraph documentation defines `Send` as its map-reduce fan-out API, TypedDict
  `Annotated` functions as per-field reducers, and `Overwrite` as the reducer bypass for reset.
  The worker is registered with the current `StateGraph.add_node(..., input_schema=...)` API so its
  payload contains only one task and JSON-safe requirements. The installed mypy surface cannot
  express that valid async callable with a narrower input schema, so the callable is cast only at
  this library boundary; runtime graph and barrier tests exercise the real registration.
- Planning-service deviation: P04's provider-running entry point remains, but plan selection,
  itinerary, cost, budget warning, context Markdown, and degradation now live in one pure
  `assemble_travel_plan_from_results()` function. The Agent Planner validates checkpoint JSON back
  into domain models and calls only that function. To keep route search independent of hotel and
  attraction branches, both P04 and P08 now query the route for the trip origin and destination;
  the old implementation queried the selected hotel to the first attraction. Route remains
  descriptive and excluded from cost.
- Failure policy: Flights and hotels are critical; missing or invalid results keep sibling state
  but prevent a plan and produce sanitized HTTP 503. Attractions, weather, and route are
  non-critical; their failures keep a `SearchErrorEnvelope` and produce a degraded TravelPlan
  whose activities and Markdown explicitly say information is unavailable.
- Verification: Focused offline P08 and compatibility tests passed 64 tests. The complete ordinary
  suite passed 185 tests with two integration tests skipped. The barrier backend released its
  Event only after all five methods entered, proving concurrent fan-out structure without using a
  timing benchmark. Explicit Docker integration passed two tests and verified PostgreSQL
  close/reopen round-trip, five unique result tasks, same-thread Tokyo-to-Paris reset, history,
  cross-thread user memory, user isolation, and strict MessagePack. Live Uvicorn acceptance
  returned HTTP 200 for a five-day Tokyo request with search counts 2/2/3/5/1, zero tool errors,
  retrieved knowledge, and two explicitly remembered preferences. A second request on the same
  thread returned a Tokyo-to-Paris plan with five unique current-request results and no old Tokyo
  destination data; the legacy Agent endpoint still returned its direct TravelPlan shape. State
  was complete, bounded history contained checkpoints, exact acceptance records were deleted and
  verified absent, and Uvicorn shut down cleanly with exit code 0. Compose parsing, all three
  infrastructure checks, and the idempotent saver/store setup passed; the existing Chroma
  `travel_knowledge` collection retained nine records. Final Ruff lint passed, Ruff confirmed 149
  Python files were formatted, mypy found no issues in 63 application files, and the complete
  ordinary suite passed 185 tests with two explicitly skipped integration tests. Enabling the
  integration marker passed two tests with 185 ordinary tests deselected.
- Remaining limitation: Providers remain deterministic invented data. There is no LLM, reviewer,
  SSE, MCP, real travel API, retry scheduler, authentication, frontend, or advanced RAG. No
  latency, throughput, or performance improvement was measured; the barrier proves graph
  concurrency, not speed.

### 2026-08-14 — Phase P09 Planner–Reviewer reflection loop

- Source intent: The architecture calls for Planner draft, structured Reviewer score/critique,
  bounded revision, and final output. The repository's original phase plan labels this work P08,
  while the current user-directed sequence completed parallel search as P08 and explicitly assigns
  reflection to P09. The current instruction controls the numbering; no advanced RAG/P10 work is
  included.
- Current LangGraph API: LangGraph 1.2.10 uses `StateGraph.add_conditional_edges()` for both the
  Planner-to-Reviewer guard and Reviewer-to-Planner/Finalize branch. `recursion_limit` is a
  standalone RunnableConfig key beside, not inside, `configurable.thread_id`. The API catches the
  official `GraphRecursionError` as a second safety boundary. Business termination still comes
  from `review_max_rounds`, so the default of three means exactly three Reviewer calls at most.
- Reviewer design: `PlanReviewer` is an async injectable Protocol. The production
  `DeterministicPlanReviewer` reads TravelPlan, requirements, search summary, retrieved context,
  remembered preferences, and tool errors without network, random values, current time, or an LLM.
  Tests inject `ScriptedPlanReviewer` only through graph construction; there is no production HTTP
  flag or test-mode backdoor.
- Scoring: Reuse P03 `QualityScore` on its existing 0–100 scale. Completeness and feasibility use
  documented fixed deductions; personalization is the percentage of reflected normalized
  preferences and gives no-preference users 100; over-budget fit is
  `round(100 * budget / total_cost, 2)`. Overall score is the equally weighted mean rounded to two
  decimals. The 80 threshold and three-round limit are Settings rather than duplicated literals.
  No user study, evaluation benchmark, or quality improvement is claimed.
- JSON and persistence: Drafts, PlanReview, RevisionPolicy, and ReviewHistoryEntry are dumped with
  Pydantic JSON mode before review-state writes and validated at node/API boundaries. Review
  history's pure reducer deduplicates by round plus SHA-256 draft fingerprint and sorts by round.
  The fingerprint covers canonical JSON for all TravelPlan fields, including Markdown. Pickle
  fallback stays disabled.
- Reset detail: `initialize_review_cycle` clears every existing review channel and old final plan
  with current LangGraph `Overwrite`, while leaving P07 memory, P06 context, and P08 search data
  intact. Because a `total=False` test input can omit a reducer channel and LangGraph cannot unwrap
  Overwrite as that channel's first ever value, a truly absent first-run field receives its raw
  safe default. API inputs explicitly initialize the fields; reused persistent threads always use
  Overwrite.
- Planning-service change: The P04 provider-running entry point and the default pure assembler
  behavior remain compatible. An optional `RevisionPolicy` can select lower-cost existing
  flight/hotel/attraction results, limit optional attraction visits, and deterministically promote
  preference-relevant existing attractions. Planner uses only saved P08 results and P06/P07
  context; it never repeats providers, RAG, or memory writes. Tests compare structured choices and
  fingerprints so a Markdown-only claim cannot count as revision.
- Failure/finalize policy: Critical search failure skips Reviewer. Non-critical degraded plans can
  be reviewed. Reviewer exception/invalid output, invalid revision, finalization failure, and graph
  recursion exhaustion use stable safe codes without raw exception text. Threshold acceptance and
  maximum-round forced finalize both validate the final draft; forced Markdown explicitly says the
  maximum was reached and never claims quality passed.
- Verification: Compose parsing passed; PostgreSQL accepted connections, Redis returned `PONG`,
  and Chroma returned HTTP 200 ready. Saver/store setup passed, all three named volumes remained,
  and `travel_knowledge` still contained nine records. The complete ordinary suite passed 225
  tests with four explicitly skipped Docker tests; explicit integration passed all four tests
  with 225 ordinary tests deselected. Ruff lint and format passed, and mypy found no issues in 73
  application files. The only warning was the existing Starlette TestClient/httpx deprecation
  warning from installed dependencies.
- Real HTTP acceptance: A normal Tokyo request completed one review at 83.33 and was accepted;
  its component scores were 100 completeness, 100 feasibility, 33.33 personalization, and 100
  budget fit. A natural 1,000 CNY request needed no production test flag: round one scored 78.97
  and requested revision, then Planner changed flight `MK920` to `MC157`, hotel `Tokyo Central
  Hotel` to `Tokyo Garden Stay`, selected lower-cost activities, and reduced total cost from
  6,300 to 4,756 CNY. Its fingerprint changed and round two passed at 80.26. A genuine 100 CNY
  request reviewed exactly three times and forced finalization at 75.53 with reason
  `max_review_rounds_reached`; its Markdown explicitly disclosed that the maximum was reached.
  Checkpoint history contained the expected Planner/Reviewer super-steps without relying on a
  fixed checkpoint count.
- Persistence acceptance: After graceful Uvicorn shutdown and a fresh process, the normal State
  and checkpoint history reopened with the same review result. A Paris request on the same thread
  reset review round/history to one, replaced the old fingerprint, and had Paris in all five P08
  result categories while the explicitly remembered crowd preference remained. A different user
  saw no preference. The P04 Mock and old non-persistent Agent endpoints both returned HTTP 200
  with their direct TravelPlan shape. The three UUID-scoped acceptance threads and one explicit
  preference were deleted and verified absent; no shared table, collection, or volume was
  deleted. The final Uvicorn process exited with code zero and port 8000 had no listener.
- Remaining limitation: This Reviewer is a transparent local ruleset, not an LLM or human. Token
  preference matching is intentionally simple, English-oriented, and not benchmarked. P09 adds no
  prompt API, Qwen/OpenAI/Anthropic integration, MCP, SSE, advanced RAG, authentication, frontend,
  real travel API, database business table, or booking action.

### 2026-08-15 — Phase P10 advanced hybrid RAG

- Source intent: Upgrade P06 into a real local semantic and lexical retrieval pipeline while
  preserving P07 persistence/memory, P08 `Send` search, and P09 review. No remote LLM, real travel
  API, MCP, SSE, authentication, or destructive data migration is included.
- Dependencies and platform: `uv add rank-bm25 sentence-transformers` resolved direct versions
  `rank-bm25==0.2.2` and `sentence-transformers==5.7.0` on CPython 3.12.13 and Apple Silicon.
  Torch 2.13.0, Transformers 5.15.0, and scikit-learn 1.9.0 are transitive dependencies;
  scikit-learn was not added directly for evaluation metrics. The public multilingual MiniLM
  model downloaded and loaded successfully on CPU and reported 384 dimensions.
- Sentence Transformers API deviation: The prompt asks for `encode_document()`, `encode_query()`,
  and the older dimension method. Version 5.7.0 provides the two retrieval encode methods but
  warns that `get_sentence_embedding_dimension()` was renamed. The adapter now prefers the
  current public `get_embedding_dimension()` and retains a public legacy fallback. It prefers
  retrieval-specific encode methods and retains `encode()` only as a compatibility fallback.
- Corpus and identity: Eight original static demo guides were added without web scraping, taking
  the corpus to 12 Markdown files. Markdown-heading parents use 1,200/150 fallback windows;
  children use 350/50 windows inside parents. The actual index has 36 parents and 77 children.
  Canonical JSON plus SHA-256 defines parent IDs, child IDs, cache keys, and the actual corpus
  fingerprint `6d9a30edca72a795c71f58f9aa63f208751ebb6d9225ca715a7795f9e33e969e`.
- Chroma API choice: Installed Chroma client 1.5.9 uses the supported local `HttpClient`,
  `get_or_create_collection(configuration=...)`, explicit `query_embeddings`, `where`, `upsert`,
  `get`, and exact-ID `delete`. The separate `travel_knowledge_children_v1` collection configures
  cosine space only; all other HNSW settings retain Chroma defaults. The old `travel_knowledge`
  collection remained present with its nine P06 records. No reset or collection deletion ran.
- Index safety: Children carry primitive Chroma metadata. Parent JSON uses Redis keys
  `rag:parent:advanced-v1:{parent_id}` plus an ignored generated local manifest. Running the
  indexer twice produced identical 12/36/77 counts and fingerprint. A fixed temporary stale child
  increased the collection to 78; the normal indexer announced one exact deletion and verified
  return to 77. No broad delete, scan, Redis flush, checkpoint removal, or volume deletion ran.
- Retrieval algorithms: The BM25Okapi tokenizer case-folds Latin tokens and uses deterministic
  CJK characters/bigrams. Four deterministic query variants retain original query first and then
  combine only validated destination/current/remembered preferences. RRF uses
  `sum(1 / (60 + rank))`; no raw BM25 score is added to vector distance. Parent reranking uses
  fixed untrained weights: normalized RRF 0.35, city 0.20, query coverage 0.20, current preference
  0.10, remembered preference 0.10, title/heading 0.05. It is not an LLM reranker.
- Redis cache/API behavior: Cache keys hash the required pipeline/fingerprint/model/query/filter/K
  configuration, use prefix `rag:cache:advanced-v1:`, and values contain final parent JSON with
  `SET ... EX 3600`. P10 adds an application-level external-operation timeout around redis-py.
  After one parent timeout, that runtime uses its local manifest for remaining parent reads.
  Real HTTP returned miss then hit for identical Chinese input; the hit kept identical parent IDs.
  The RAG status/search endpoints return safe local diagnostics and deliberately have no
  authentication.
- Graph/persistence behavior: Lifespan creates the model, BM25, manifest stores, cache, and
  retriever once without downloading or indexing. LangGraph State contains only final contexts,
  variants, parent IDs, JSON-safe diagnostics, and a safe error. Reused-thread fields use
  `Overwrite`; P09 revision does not rerun RAG. Reviewer receives retrieval unavailability as a
  non-critical data issue. Strict MessagePack tests contain no vectors or clients.
- Evaluation deviation and result: Production returns four parents, so the transparent local
  metrics run at `K=4` rather than the prompt's suggested `K=5`. Twenty-four fixed English/Chinese
  queries have manually written graded parent labels from the current index. Actual macro results
  were: dense `P=.406250, R=.704861, MRR=.732639, NDCG=.617939`; BM25
  `.250000, .416667, .534722, .404095`; hybrid RRF
  `.250000, .423611, .531250, .409361`; hybrid reranked
  `.375000, .642361, .788194, .691358`. Hybrid reranked improved MRR/NDCG over dense on this
  fixture but reduced Precision/Recall; no general quality or performance improvement is claimed.
- Actual acceptance: Chinese retrieval returned four unique Tokyo parents with dense and sparse
  candidates and no embedding payload. Paris filtering returned four Paris parents. A persistent
  Tokyo plan retained P08's five results and P09's one-round accepted review; its second same-thread
  Paris request had zero parent-ID overlap, reset review history to one, and retained the explicit
  remembered preference. With Redis stopped, a new request returned in 6.07 seconds with
  `cache_status=unavailable`, dense/sparse results, and four Paris parents from local fallback.
  Redis was restored and all three infrastructure probes passed.
- Final verification: Ruff lint and format passed, mypy found no issues in 90 application files,
  and ordinary pytest passed 268 tests with six explicitly skipped Docker tests. Explicit
  integration then passed all six tests with 268 ordinary tests deselected. The only warning was
  the existing Starlette TestClient/httpx deprecation warning. Both temporary Uvicorn processes
  shut down cleanly and port 8000 had no listener afterward.
- Limits: The corpus and judgments are small local fixtures, not live travel facts or a production
  benchmark. Deterministic expansion/reranking is replaceable architecture, not real LLM use.
  Current hours, prices, inventory, weather, transport notices, and accessibility must be verified
  externally. The existing Starlette TestClient/httpx deprecation warning remains.

### 2026-08-16 — Phase P11 local MCP travel-tool layer

- Source and phase intent: The original phase plan places MCP earlier and labels later persistence
  work as P11. The current user-directed sequence has completed persistence, parallel search,
  reflection, and advanced RAG as P07–P10 and explicitly assigns MCP to P11, so the current prompt
  controls numbering. No P12, SSE, LLM tool selection, real provider, MCP resources/prompts,
  sampling, elicitation, OAuth, or public deployment was added.
- Resolved APIs: `uv add` resolved FastMCP 3.4.7, `langchain-mcp-adapters` 0.3.2, and the official
  MCP SDK 1.29.0. FastMCP STDIO uses `mcp.run()`; Streamable HTTP uses
  `mcp.run(transport="http", host="127.0.0.1", port=..., path="/mcp")`. The adapter uses
  `MultiServerMCPClient`, `transport="stdio"` and documented `transport="http"`, then
  `await client.get_tools()`. It is configured with `handle_tool_errors=False` so the application
  owns safe error mapping.
- Structured output: A real adapter 0.3.2 HTTP call was executed. `BaseTool.ainvoke()` returned a
  public LangChain `ToolMessage`; its public `artifact` was a dict containing only
  `structured_content`, whose value was the complete `MCPToolResponse`. The decoder prefers that
  field and also strictly supports a complete JSON string and the adapter's one-text-block
  fallback. It uses no private classes, regex extraction, or raw-payload echo.
- Architecture: Independent `travel-local-tools` STDIO and `travel-search-tools` HTTP FastMCP
  Servers reuse the P03 provider functions through `asyncio.to_thread()`. A name-based registry
  rejects duplicate, missing, and unexpected tools. A bounded invoker applies an eight-second
  default timeout and at most one retry to transient transport failures. `MCPTravelSearchBackend`
  implements the existing P08 `SearchBackend`, so Search Worker, five-way `Send`, reviewer, RAG,
  checkpoints, and memory do not select or store MCP objects.
- Route boundary deviation: The existing P08 `SearchBackend.get_route(origin, destination)` does
  not receive the full trip requirements. To preserve that stable Protocol and avoid modifying
  Search Worker or existing test backends, the MCP backend creates a deterministic internal
  one-day requirements carrier solely for route request metadata; the route provider still
  receives exactly the caller's origin/destination, and the carrier is never returned or written
  to graph state. Other four tools serialize the actual `TripRequirements`.
- Lifecycle and readiness: direct remains the default and does not create an MCP client or STDIO
  process. MCP mode discovers once before graph compilation, then reuses its registry. Discovery
  failure does not block FastAPI startup and never silently falls back to direct. Readiness uses
  cached discovery, a loopback socket check, and a one-second refresh cooldown. Current
  `MultiServerMCPClient` exposes no public `aclose()`; its documented stateless tool sessions
  create and clean up their own connections, so no private close attribute is called.
- Security and limits: The HTTP Server binds only 127.0.0.1, sends no Authorization header, and is
  unauthenticated local-development functionality. Fixed STDIO command/args use `sys.executable`,
  a fixed module, fixed project cwd, and a minimal safe environment without Token, password, or
  DSN forwarding. Diagnostics omit command, URL, PID, environment, tool/client repr, traceback,
  and secrets. All outputs remain invented deterministic mock data; no quality, speed, QPS, or
  production-readiness improvement is claimed.
- Actual verification: `uv sync` resolved 179 packages and checked 148 installed packages. The
  explicit smoke discovered two STDIO and three Streamable HTTP tools and successfully called all
  five. MCP-mode status reported both Servers ready and five unique tools; `/health` and `/ready`
  returned 200. A persistent Shanghai-to-Tokyo request and same-thread Tokyo-to-Paris request both
  returned 200 with five successful search kinds, P10 parent context, one P09 review round, and the
  explicitly remembered preference; the final state was `mcp`, Paris, five results, and one review
  history entry. After HTTP MCP stopped, readiness returned 503, health remained 200, Agent returned
  a sanitized `critical_search_failed` 503, and checkpoint state kept two successful STDIO results
  plus three HTTP errors. Restarting HTTP MCP restored discovery/readiness and the same failed
  thread reset to five results and zero errors. A new FastAPI process restored the Paris state and
  preference from PostgreSQL. With the MCP Server stopped, default direct mode still returned
  readiness 200 and a complete five-result reviewed plan without starting STDIO. Three acceptance
  threads and one acceptance preference were deleted by exact test identifier; no volume was
  removed. Final Ruff lint/format and mypy passed, ordinary pytest passed 302 tests with seven
  explicit integration skips, the isolated P11 integration passed one test, and all integrations
  passed seven tests. The sole suite warning remains the pre-existing Starlette TestClient/httpx
  deprecation warning.

### 2026-08-17 — Phase P12 SSE progress streaming

- Source intent: Safely project the existing persistent LangGraph progress and final TravelPlan
  into one cancellable SSE response. P12 does not add token streaming, an LLM, a frontend,
  observability, authentication, replay, a business lock, or a second graph execution.
- Resolved versions and Graph API: Local imports reported Python 3.12.13, FastAPI 0.141.1,
  Starlette 1.4.1, LangGraph 1.2.10, langchain-core 1.5.3, and Pydantic 2.13.4. The public compiled
  graph signature supports `stream_mode=["tasks", "updates"]` and `version="v2"`. A real in-memory
  graph probe produced v2 envelopes shaped as `{"type": "tasks"|"updates", "data": ...}`. Task
  starts had `id/input/name/triggers`; finishes had `id/name/result/error/interrupts`; updates were
  `{node_name: node_update}`. The probe observed five search-worker starts and five finishes in the
  same graph execution.
- FastAPI SSE choice: Use current native `EventSourceResponse` and `ServerSentEvent`, so FastAPI
  owns standards-compliant `id`, `event`, JSON `data`, comment framing, `text/event-stream`,
  `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and its request-scoped structured teardown.
  Its current wire encoder writes the legal field order `event`, `data`, then `id`; SSE parsers
  treat fields by name, so this is behaviorally equivalent to the source example's `id`, `event`,
  then `data`. P12 does not replace the supported encoder merely to rearrange semantically
  unordered lines.
  FastAPI 0.141.1 has a fixed internal 15-second keepalive and no public ping-interval argument.
  Rather than patch its private constant, P12 uses a validated 10-second application comment
  heartbeat (configurable up to 14 seconds); FastAPI's native ping remains a later fallback.
- Backpressure and cancellation: An application-owned bounded `asyncio.Queue` defaults to 64.
  Business puts await capacity and are never dropped. FastAPI adds its native capacity-1 transport
  buffer. Disconnect cancellation reaches the response generator; its `finally` cancels and
  awaits the graph producer. The producer closes the one `astream` async generator. Expected
  `CancelledError` is suppressed only while awaiting cancellation cleanup, and client disconnect
  does not create a terminal business event. The private completion sentinel uses non-blocking
  insertion: if a disconnected consumer left the bounded queue full, cleanup cannot deadlock on a
  second awaited put. Connected success and failure paths exit from their terminal business event.
- Safe mapping: `tasks` owns allowlisted node start/finish and five search lifecycles. `updates`
  owns only retrieval, review, revision, and validated final-plan facts. Unknown nodes and all raw
  task input/result/config/state are ignored. Search output contains only kind/status/count or a
  stable safe error. Retrieval output excludes context, IDs, cache keys, embeddings, corpus/model
  details, candidates, and scores. Reviewer facts come from validated `PlanReview`; the final plan
  comes from `TravelPlan.model_validate()`.
- Terminal and persistence semantics: A per-connection sequencer starts at one and assigns both ID
  and sequence with an aware UTC timestamp. A terminal guard allows exactly one
  `plan_completed` or `error`. Normal final output comes from the one stream's `finalize_plan`
  update. Only when that is absent and no error was observed may `aget_state()` read the same
  thread's saved checkpoint. A fallback plan must exactly match the current request requirements,
  so a reused thread cannot return an older destination's plan. Streaming code contains no
  `ainvoke()` fallback. The old non-stream endpoint retains its original single `ainvoke()`
  behavior.
- Automated verification: P12 models, mapper, service, cancellation, HTTP comment heartbeat,
  real in-memory graph API, SSE framing, state/history, preference memory, natural revision, safe
  failure, full-queue cleanup, same-thread Tokyo-to-Paris replacement, and checkpoint-fallback
  tests passed 30 focused tests; the two P12 integration tests
  were explicitly skipped without `RUN_INTEGRATION_TESTS=1`. Ruff lint and format passed, and
  mypy found no issues in 108 application files. The complete ordinary suite passed 332 tests
  with nine explicit integration skips. The isolated P12 integration passed two tests against
  real PostgreSQL/Redis/Chroma and dynamic-port STDIO/HTTP MCP, including durable same-thread
  Tokyo-to-Paris replacement. The only warning remained the existing Starlette TestClient/httpx
  deprecation warning.
- Live direct acceptance: Compose started the existing three containers without deleting volumes;
  PostgreSQL accepted connections, Redis returned PONG, Chroma returned HTTP 200 ready, and saver
  and store setup passed. A real curl direct stream produced 32 monotonic business events with
  all five search kinds, retrieval, review, and exactly one validated Tokyo `plan_completed`.
  Its saved state was complete with five search results, one accepted review, four query variants,
  four parents, 12 inspected history items, and one explicit preference. The existing advanced
  index remained ready with 36 parents and 77 children. A separate natural five-day 1,000 CNY
  request produced review score 78.97/revise, `revision_started`, then 80.26/accept and successful
  finalization. These deterministic fixture scores are observations, not a quality benchmark.
- Live cancellation and MCP acceptance: Curl disconnected after 55 milliseconds with six partial
  business events; it had `run_started` but no `error` or `plan_completed`, and Uvicorn logged no
  unhandled/pending/unclosed task or session warning. Real MCP smoke discovered and called all five
  tools. MCP-mode readiness was ready with five tools; its curl stream produced 32 business events,
  all five search kinds, one validated terminal plan, and a complete five-result checkpoint with
  no MCP object names. Stopping the HTTP MCP Server made a new stream return safe JSON HTTP 503
  `stream_backend_unavailable` before `run_started`, with no direct fallback or transport detail.
  Both Uvicorn processes and the MCP Server shut down cleanly; ports 8000 and 9001 and the filtered
  project server process list were empty afterward.
- Acceptance cleanup and caveat: Five actual `p12-manual-*` checkpoints and one exact manual
  preference were removed and verified absent; the outage request had created no checkpoint. No
  table, collection, cache, container, or named volume was deleted. A one-off low-level saver
  existence probe printed strict serializer blocked-deserialization notices for Currency,
  TravelPlan, and TripRequirements; the normal API restart path and integration test restored
  typed state successfully. This diagnostic caveat does not change the strict no-pickle policy.

### 2026-08-19 — Phase P13 observability baseline

- Source intent: Add low-cardinality Prometheus metrics, safe structured logs, full-response HTTP
  and SSE timing, an optional local Prometheus/Grafana stack, and explicit full-E2E verification
  without changing the deterministic travel workflow.
- Implemented approach: Use the already-declared Loguru 0.7.3 and prometheus-client 0.26.0. Each
  FastAPI app owns a fresh `CollectorRegistry`; the pure ASGI middleware sits outside FastAPI's
  final error-response layer so normal responses, 404/503, safe 500 responses, full streaming
  bodies, and disconnect cleanup share one request ID and duration. Graph execution is counted at
  the existing `ainvoke()`/`astream()` call sites, while node, RAG, search, MCP, reviewer, and SSE
  wrappers observe only the work already being performed. No wrapper calls the graph a second
  time, and search wrappers do not join or reorder the five LangGraph `Send` branches.
- API and privacy deviation: The source description permits raw thread/user correlation only when
  safe. This implementation never logs raw values; optional `thread_ref`/`user_ref` fields are a
  stable SHA-256-derived pseudonym, which is correlation rather than anonymization. They never
  become metric labels. Logs use a strict public field allowlist and omit request bodies, plans,
  RAG context, MCP payloads, raw exceptions, tracebacks, credentials, DSNs, and connection URLs.
- Container choice: Prometheus uses the official `prom/prometheus:v3.14.0` image and Grafana uses
  the maintained official `grafana/grafana:13.1.3` image, both fixed rather than `latest` and both
  published for arm64. Grafana's older `grafana/grafana-oss` repository is deliberately not used.
  The `observability` profile preserves the default three-service startup, binds 9090/3000 only to
  loopback, provisions immutable datasource/dashboard UIDs, and retains data for seven days in
  named local volumes.
- Verification: Both default and profile Compose configurations parsed successfully. The pulled
  images were real arm64 manifests; all five services started, both new healthchecks passed, and
  the checker reported 7/7 PASS with Prometheus target UP plus the fixed Grafana datasource and
  20-panel dashboard. Prometheus observed three direct graph successes, three successes for each
  of the five direct Search kinds, zero active SSE connections, and ready infrastructure gauges.
  A separate real MCP run discovered STDIO and HTTP tools, returned HTTP 200, and exposed exactly
  one success for the MCP graph, each Search kind, and each of the five MCP tools, with both MCP
  dependency gauges at 1. The final ordinary suite passed 352 tests with 10 explicit skips; real
  integration passed 9 tests with the separately gated P13 test skipped; the final observability
  run passed its one live E2E. Ruff lint/format and mypy passed. The sole warning is FastAPI's
  upstream TestClient notice that its current httpx integration is deprecated in favor of
  `httpx2`; it does not indicate a P13 behavior failure.
- Current limitation: Metrics are process-local and support one Uvicorn worker only; Python
  Prometheus multiprocess mode is not configured. There is no production authentication, TLS,
  alerting, on-call integration, LangSmith/LLM tracing, or real travel inventory. The local
  anonymous Grafana Viewer is unsuitable for public exposure.
- Final review correction: Loguru is process-global, so application lifespans now acquire unique
  leases on one compatible shared sink. Reference counting prevents a nested app shutdown from
  removing a still-active app's sink, duplicate release is harmless, and conflicting overlap fails
  explicitly. Request-ID bytes must decode as strict ASCII, the HTTP body is complete only after
  the final ASGI send succeeds, and SSE success/error is committed only after downstream resumes
  past the terminal event; these boundaries keep cancellation/disconnect metrics truthful. The
  redactor also consumes complete Authorization/Cookie header lines and driver-qualified
  PostgreSQL DSNs instead of leaving later header values or credentials visible.

### 2026-08-25 — Phase P14 grounded Qwen reasoning

- Source intent: Add real Qwen reasoning without replacing P08 search concurrency, P09 loop safety,
  P10 retrieval, P11 fixed MCP tool mapping, P12 progress SSE, or P13 privacy boundaries. The
  default remains deterministic and initializes no model client.
- Current API choice: Use Alibaba Cloud Model Studio's official OpenAI-compatible Chat Completions
  API through `openai` 3.3.1. JSON tasks use `response_format={"type":"json_object"}` and
  `extra_body={"enable_thinking":false}`. The SDK's own retries are disabled; the provider applies
  the project's bounded retry policy so two independent retry layers cannot multiply calls.
- Real-output deviation: Model Studio JSON mode guarantees parseable JSON, not adherence to a
  Pydantic class name that exists only in Python. Initial real acceptance therefore exposed one
  schema-validation failure. Planner and Reviewer prompts now include their exact bounded output
  contracts, and the Planner repeats only the current candidate IDs and required day numbers in a
  compact authoritative allowlist. Local Pydantic and grounding validation remains strict; it was
  not weakened to accept invented fields or candidates. Safe grounding diagnostics record only a
  fixed reason category while the public error stays `llm_grounding_violation`.
- Endpoint deviation and safety: Rather than accepting arbitrary compatible endpoints, Settings
  requires HTTPS and current official DashScope or documented regional workspace/trial
  `maas.aliyuncs.com` hosts with the exact compatibility path. This preserves provider flexibility
  while preventing a key from being sent to localhost, an IP, or an untrusted hostname.
- Planner architecture: Qwen returns only stable SHA-256-derived candidate IDs and a per-day
  attraction schedule. Application validation resolves exact original provider objects, rejects
  unknown/duplicate candidates and revision-policy bypass, then calls the existing deterministic
  assembler for dates, facts, and costs. Provider data models were not modified.
- Reviewer architecture: Qwen returns four bounded dimensions, critique, issue codes, and advisory
  changes. Application code computes the equal-weight overall score and retains P09's threshold,
  maximum rounds, forced finalization, and issue-code-to-RevisionPolicy mapping. Raw model output,
  SDK objects, exceptions, prompts, and hidden reasoning are not checkpointed.
- Optional work deliberately omitted: Qwen query expansion and LLM MCP tool selection are not
  implemented. Existing deterministic multi-query retrieval and fixed five-tool mapping are
  already stable; adding calls would increase cost and variability without being required for
  Planner/Reviewer reasoning.
- Observability and fallback: New metrics use only role/status or input/output labels. Tokens are
  counted only from real SDK usage. Deterministic fallback is disabled by default and, if explicitly
  enabled, produces a visible fallback metric and safe log rather than a false Qwen success.
- Remaining limitations: Qwen reasons over local mock search data and demo RAG evidence. It does
  not provide live inventory, verified prices, booking, payment, authentication, frontend, or
  token-level SSE streaming. Real API availability and model entitlement require the separately
  gated smoke/integration checks and are never inferred from offline tests.
- Actual P14 verification: The focused offline suite passed 48 tests, strict mypy reported no
  issues in 127 application files, Ruff format passed, and the full ordinary suite passed 400
  tests with 11 explicit integration skips. With the five local containers available, the
  deterministic infrastructure integration suite passed 9 tests with one separately gated
  observability test skipped. Real Prometheus query parsing accepted all four LLM dashboard
  expressions after substituting Grafana's rate interval with five minutes.
- Real-provider acceptance: A separately gated, locally configured Singapore workspace used
  `qwen3.7-plus`; no endpoint or credential was recorded. The explicit smoke response passed its
  strict schema with SDK-reported usage of 39 input and 5 output tokens; the command's wall-clock
  time was about 2.72 seconds and is not a latency benchmark. Real acceptance initially exposed the
  JSON-contract issue above and then a grounding rejection; after the minimal prompt/allowlist
  correction, the gated persistent Planner/Reviewer invariant test passed.
- Real streaming acceptance: One unique persistent Qwen-mode SSE request completed with 44
  strictly sequenced business events, five search categories, Planner and Reviewer progress,
  exactly one final `plan_completed`, no business `error`, and exactly one successful graph run.
  The application-controlled loop used three Planner and three Reviewer calls before forced
  finalization at the configured maximum. The SDK reported 8,538 input and 2,260 output tokens for
  this single streaming workflow. Public state, 16 readable checkpoint-history entries, four RAG
  parent results, and the explicitly remembered preference survived strict MessagePack recovery;
  no SDK client, raw completion, prompt, authorization value, secret, or DSN appeared in the public
  state or captured structured logs. These numbers describe only this acceptance run and are not
  performance, quality, cost, or production-readiness claims.
- Final review correction: Model Studio's current OpenAI-compatible documentation marks
  `max_tokens` for deprecation and recommends `max_completion_tokens`. The provider now passes a
  validated `QWEN_MAX_COMPLETION_TOKENS` value (default 2048, allowed 256–4096), while keeping the
  SDK retry layer disabled and the application retry count bounded. Strict JSON parsing now rejects
  duplicate object keys, non-standard NaN/infinity constants, and numeric-string coercion instead
  of accepting Python/Pydantic's permissive defaults. Prompt DTO string items have their own bounds;
  common bearer/key/DSN shapes are redacted; and angle brackets in untrusted JSON are escaped so
  delimiter text cannot close its data block. Qwen model IDs are also pattern-limited before their
  safe status/log exposure, and the shared log redactor now recognizes a bare `sk-...` key shape.
  Finally, an explicitly enabled Qwen-to-deterministic fallback records both Planner and Reviewer
  use even when startup had no provider, rather than making the Reviewer fallback silent. These
  changes do not alter candidate grounding, graph topology, checkpoint format, or P12's
  single-execution SSE design.
- Integration isolation correction: The first final-review Docker run inherited the local
  qwen-mode `.env`, so two pre-P14 integration tests unintentionally made nine real structured
  model calls. No secret, prompt, or completion was logged, and the calls confirmed the new
  completion-limit parameter was accepted, but `RUN_INTEGRATION_TESTS=1` is not the paid-model
  opt-in. Those in-process readiness/direct-SSE tests now explicitly select deterministic mode;
  only the separate `RUN_LLM_INTEGRATION_TESTS=1` gate can enable the real Qwen invariant test.
- Final review verification: The focused P14 plus logging suite passed 67 tests. Ruff lint and
  format checks passed, strict mypy reported no issues in 127 application files, `git diff --check`
  passed, and the final ordinary suite passed 414 tests with 11 explicitly gated skips. After the
  isolation correction, the Docker integration suite passed 9 tests with 2 independently gated
  tests skipped and emitted no LLM request logs. The final separately enabled real Qwen
  Planner/Reviewer invariant passed once in 50.94 seconds. That duration is only this command's
  wall-clock observation, not a latency benchmark or production claim.

### 2026-08-26 — Phase P15 conversational intake

- Source intent: Add recoverable multi-turn requirement collection before the existing planning
  graph. The implementation uses the existing PostgreSQL Store namespace
  `(user_id, "trip_intake")` with `thread_id` as key; partial data never enters the LangGraph
  checkpointer, and a successful intake stores only a small plan-availability reference.
- Domain-model finding: The current `TripRequirements` model requires origin, destination,
  start/end dates, budget, and travelers. Currency has a real `CNY` default and preferences have an
  empty-list default, so P15 derives its required-field list from Pydantic rather than treating the
  source prompt's possible currency list as authoritative.
- Date/API choice: Intake dates use the project's inclusive itinerary semantics. The intake-only
  `duration_days` range is 1–366 to match P14's bounded per-day structured output. Ambiguous month
  input remains missing; exact date arithmetic and final domain validation stay in application
  code rather than trusting model arithmetic.
- Provider choice: `StructuredLLMProvider` gains incremental extraction, but the P14 lifespan still
  owns exactly one `AsyncOpenAI` client and one bounded retry layer. Model Studio JSON-object mode
  does not enforce the local Pydantic schema, so duplicate-key/NaN/infinity rejection, strict
  numeric types, unknown-field rejection, Pydantic validation, and prompt boundaries remain local.
- Consent and execution: Qwen may only produce `TripRequirementPatch`; it cannot confirm, plan,
  use tools, or write memory. Canonical effective draft JSON is SHA-256 fingerprinted. Both confirm
  endpoints require the current fingerprint and reuse the existing non-stream execution or P12
  `TravelPlanStream`; no second planning graph or SSE mapper was introduced.
- Security and persistence: Only the current draft, current UTC date, and current redacted message
  reach Qwen. Credential-shaped message text is redacted before both prompt forwarding and bounded
  user-visible history persistence. Logs and metrics exclude raw message, draft, preferences,
  prompt, completion, user ID, and thread ID.
- Deliberate limitation: LangGraph Store does not expose compare-and-swap for this key. P15 returns
  an incrementing version and blocks stale confirmation by fingerprint, but callers must serialize
  mutations for the same user/thread. No Redis distributed lock was added. Deterministic runtime
  returns `conversational_intake_requires_llm` for conversation messages while every older complete-
  JSON deterministic endpoint remains available.
- Actual P15 verification: The focused offline intake suite passed 50 tests. Ruff formatting,
  linting, strict application mypy, and `git diff --check` passed; the full ordinary suite passed
  464 tests with 12 explicitly gated skips. With local containers healthy, the real PostgreSQL
  restart/user-isolation intake test passed, followed by the full deterministic infrastructure
  suite with 474 passes and 2 independently gated skips. The observability checker saw all 14 key
  metric families, an UP Prometheus target, and the provisioned 28-panel dashboard; Prometheus's
  HTTP API parsed each of the four new P15 panel expressions successfully.
- Real-provider acceptance: The single separately gated P15 test passed once. It used two real
  intake turns followed by one explicit confirmation stream, then asserted strict extraction,
  zero planning before confirmation, five fixed search categories, grounded Planner/Reviewer
  output, one successful `plan_completed`, readable checkpoint state, and persisted `planned`
  intake state. Pytest's wall-clock result was 54.17 seconds; this is one acceptance observation,
  not a latency, quality, cost, or production-readiness claim. The test did not print the key,
  prompt, or completion and its `finally` block removed its UUID-scoped checkpoint, intake, and
  preference records.

### 2026-08-27 — Phase P16 web chat frontend

- Source intent: Turn P15 intake and P12 workflow streaming into one browser journey without a
  second backend. The implementation is a React/TypeScript Vite SPA under `frontend/`; all browser
  requests remain relative and Vite proxies them to FastAPI. FastAPI CORS, intake, graph, RAG, MCP,
  persistence, and SSE code are unchanged.
- Current API choice: The official Tailwind v4 integration uses `@tailwindcss/vite` plus one CSS
  import instead of the older source-style PostCSS/config pseudocode. React 19.2, Vite 8.2, and
  Tailwind 4.3 were the current stable lines verified from official documentation and npm. The
  installed Node 24 runtime satisfies Vite 8. TypeScript is intentionally pinned to the current
  6.0 line because `typescript-eslint` declares support below 6.1; blindly taking TypeScript 7
  would exceed that peer range.
- Streaming choice: Browser `EventSource` cannot send P15's required POST body. A small fetch/
  ReadableStream parser handles arbitrary UTF-8 chunks, LF/CRLF, multi-line data, and final flush.
  The existing `: ping` remains a transport comment, never enters React state, and consumes no
  business sequence. Known payloads pass strict Zod validation; unknown future event names are
  ignored.
- Persistence/security boundary: localStorage holds only a random demo user UUID, a current thread
  UUID, and at most ten thread metadata records. It never holds messages, plans, model output,
  preferences, keys, or backend environment data. Reload reads P15 conversation and existing safe
  thread state; it never reruns the graph. No frontend source contains a Qwen key, DSN, bearer
  secret, or direct infrastructure/model call.
- Deliberate limitations: This is local demonstration UX with no authentication. Travel options
  remain deterministic sample data, there is no booking or payment, SSE has no replay, and the
  stream reports workflow progress rather than real model tokens. Real browser/Qwen acceptance is
  separately gated and excluded from ordinary tests.

### 2026-08-28 — Phase P17 Duffel external travel data

- Provider correction: The earlier Amadeus direction is not implemented because its Self-Service
  APIs were decommissioned on 2026-07-17. P17 instead uses the current official Duffel REST API,
  bearer access tokens, fixed host `https://api.duffel.com`, and `Duffel-Version: v2`. No OAuth
  client-secret exchange or third-party Duffel SDK was added; the already-direct `httpx 0.28.1`
  dependency provides the async transport and MockTransport test seam.
- Data/transport separation: `TRAVEL_DATA_MODE=demo|duffel` controls facts, while the existing
  `TRAVEL_SEARCH_BACKEND_MODE=direct|mcp` controls how the application reaches the five tools.
  Duffel mode replaces only flights and hotels; attractions, weather, and route remain demo.
  FastAPI direct mode owns one shared AsyncClient in its lifespan. The independent HTTP MCP server
  creates and closes its own runtime from its own environment and never receives a token in tool
  arguments.
- Official endpoint choices: Flight search creates one one-way `/air/offer_requests` request and
  explicitly sends `return_offers=true&view=offers` and validates the documented top-level `data`
  Offer Request with its embedded `offers`. Location resolution uses `/places/suggestions` rather
  than an LLM or a small hard-coded airport list. Stays uses `/stays/search` with official
  geographic coordinates, dates, adult guests, and one room. P17 never calls Flight Orders, Stays
  Bookings, payments, or quotes for booking.
- Date and price semantics: Project `end_date` is inclusive, while Stays `check_out_date` is
  exclusive, so the adapter sends `end_date + 1 day`. Duffel's cheapest stay amount is the total
  for the room, all nights, and all guests; mapping divides that Decimal by the inclusive trip-night
  count and rounds to cents. Initial support is deliberately one room and one or two adults; larger
  parties fail with `duffel_unsupported_request` rather than showing a misleading price.
- Mapping honesty: Every operating flight segment is retained with full operating-carrier name,
  IATA endpoints, timestamps, duration, and stop count. Offer ID/expiry are metadata only. Hotel
  property rating remains nullable and distinct from nullable review score; missing amenities map
  to an empty list, and distance is derived by Haversine only when coordinates exist. Unsupported
  currencies fail because P17 does not invent an FX conversion.
- Real-schema correction: The first real test-mode Flights smoke reached Duffel successfully but
  returned `duffel_invalid_response`. The earlier sanitized fixture always supplied string
  durations and empty airport lists. Current Duffel v2 schemas instead declare offer-slice and
  segment `duration` as nullable and ISO 8601, and Places `airports` as a nullable list. External
  response models now ignore unused vendor additions, retain strict types for consumed data, model
  both carrier flight numbers as strings and carrier/place values as objects, and accept documented
  nulls. A null flight duration is derived only from the nested airport IANA time zones and local
  schedule; it is never guessed. Schema diagnostics retain and log only provider, operation, error
  count, Pydantic `loc`, and Pydantic `type`; the validation input and exception cause are discarded.
  The single post-correction real Flights call exposed three non-string operating flight-number
  locations and three slice-duration strings outside the earlier hour/minute regex. Values remained
  intentionally hidden. The model therefore accepts only string-or-null for the operating number
  (never integer coercion), falls back to the strict marketing number when null, and uses Pydantic's
  ISO 8601 `timedelta` validation for positive non-null durations, including day components.
  That one real call still returned `duffel_invalid_response`; it was not repeated after these final
  corrections. That earlier focused Duffel suite passed 48 offline tests; the ordinary suite passed
  518 tests with 14 skips. This historical pending status is superseded by the user's later real
  Flights successes: latest 70 offers, earlier 71, 75 and 81. Duffel Flights Developer Test is
  user-verified. Stays access remained unapproved through 2026-09-08 and is not a P17 gate.
- Retry deviation: The phase source broadly suggested retrying temporary 5xx responses. Current
  Duffel response-handling documentation explicitly recommends retrying 503/504 and not retrying
  500/502. The client therefore retries only timeouts, transport failures, 429, 503, and 504, with
  one retry by default and a two-second cap on the `ratelimit-reset` delay. 400/401/403, malformed
  JSON, and schema failures do not retry.
- Provenance/fallback: Search summaries, persisted domain results, final plans, SSE search-complete
  events, metrics, MCP envelopes, and the frontend use the fixed sources `demo`, `duffel_test`,
  `duffel_live`, and `demo_fallback`. Fallback defaults off. When explicitly enabled it is logged,
  counted, persisted, and labeled; a Duffel failure is never silently presented as external data.
  Volatile offer expiry/search IDs and source labels are excluded from grounded candidate identity.
- Readiness/security: `/api/v1/travel-data/status` performs no remote request and exposes no token
  prefix. Missing token in Duffel mode makes `/ready` and pre-stream validation fail, while
  `/health` remains a local liveness response. Authorization headers, raw responses, external
  objects, and exceptions never enter graph state, checkpoints, SSE, metrics, frontend, or logs.
  Real tests are isolated behind `RUN_DUFFEL_INTEGRATION_TESTS=1`; ordinary and Docker integration
  suites remain offline with respect to Duffel.
- Initial P17 verification: Ruff lint and format checks passed, strict mypy found no issues in 148
  application files, and the ordinary offline suite passed 512 tests with 14 explicitly gated
  skips. With PostgreSQL, Redis, and Chroma available, the ordinary integration suite passed 10
  tests with one independently gated test skipped and 515 tests deselected; it did not select or
  contact Duffel. Vitest passed 59 tests in 11 files, the production frontend build passed, and
  Playwright passed two desktop/mobile mock journeys with two real-backend journeys skipped.
  At that time `DUFFEL_ACCESS_TOKEN` was not configured, so the no-credential smoke checker failed
  fast with a safe configuration message, as designed. A later user-executed Flights-only smoke
  reached the real test environment but exposed the schema mismatch recorded above. Real Duffel
  Stays and the full mixed-source Agent path were **NOT VERIFIED** and were not attempted during
  that focused Flights diagnosis. The final acceptance below supersedes the mixed-Agent status.

### 2026-09-08 — P17 continuation: Duffel Flights + LiteAPI Hotels

- Source intent changed explicitly: retain verified Duffel Flights, replace required Stays with
  LiteAPI/Nuitee Connect hotel search. Existing uncommitted Duffel work is preserved; Stays is an
  optional adapter with NOT VERIFIED real acceptance (approval pending through 2026-09-08).
- New `external` mode separates flight/hotel selectors; demo overrides both; legacy `duffel`
  still selects Flights + Stays. Shared Duffel Places resolution means LiteAPI hotels also need
  the Duffel location credential even if flights are demo. Status/readiness disclose this locally.
- Current official LiteAPI v3 rates API uses a fixed trusted host and X-API-Key. Response metadata
  is top-level `hotels[]`, joined to rates `data[]` by property ID, not invented nested hotelData.
  References and exact field/price contracts are in `24_EXTERNAL_TRAVEL_DATA.md`.
- External projection models ignore unused fields but strictly validate consumed fields. Amounts
  are parsed into Decimal from numeric JSON. No raw JSON, headers, rate IDs or unbounded remarks
  enter domain models. Bounded loc/type diagnostics reuse the Duffel safety pattern.
- P15 nationality is an optional explicit ISO alpha-2 field with deterministic conditional
  clarification/confirmation. It is not inferred and is not automatically saved as user preference.
- Existing dates are inclusive (P15 duration − 1, P04 daily itinerary and per-day hotel budget).
  Oct 12–16 therefore maps to five nights and checkout Oct 17. Tests span those layers. Exact
  stay totals are retained to avoid multiplying rounding error from the nightly average.
- Included taxes are not added twice; separately payable fees set an honest bounded UI warning.
  Nullable stars/reviews/amenities/distance are not fabricated. One room, one or two adults only.
- One HTTP pool/provider/process; bounded provider retry owns retry policy. MCP gets sufficient
  deadline budget and no outer external retry to prevent repeating costly provider work.
- Safe sources now include LiteAPI sandbox/production. Final SSE clears offer/search identifiers
  in an output-only copy, preserving internal checkpoints and the single-graph-run invariant.
- Ordinary integration MCP subprocesses explicitly receive demo mode, preventing a private
  external .env from accidentally spending requests during local Docker acceptance.
- Final review fixes: persistent non-stream planning now shares the same local credential and
  nationality preflight as SSE; duplicate properties compare exact stay totals; explicit demo
  fallback is capped before entering graph state; LiteAPI can use an official IATA code when
  shared location resolution lacks coordinates, while the legacy Duffel default is unchanged.
  Regression tests also cover MCP source crossover/caps, wrong occupancy, inconsistent quote
  totals, environment/key-prefix mismatch, HTTP 204, and smoke gates with no HTTP construction.
- Executed 2026-09-08: targeted offline suite 243 passed; Ruff lint/format passed (350 Python
  files formatted); mypy passed 159 app files; full pytest 604 passed/15 skipped; explicit local
  integration 10 passed/1 skipped/608 deselected. Frontend lint/typecheck/build passed; Vitest
  60 tests in 11 files passed; Playwright 2 mock desktop/mobile passes and 2 real-backend skips.
- Earlier acceptance gate (superseded by the final verification below): the LiteAPI checker was invoked once and returned exit 1,
  `FAIL LiteAPI configuration: liteapi_not_configured`. It made zero external HTTP requests.
  At that point LiteAPI sandbox result count and full mixed real Agent/SSE were NOT VERIFIED. Per the requested
  sequence, no further Duffel, Stays or Qwen calls were made. A private sandbox-key configuration
  was needed before real acceptance could resume. This historical result is not the current status.
- Infrastructure checks passed: PostgreSQL accepting connections, Redis PONG, Chroma HTTP 200
  with executor/log client ready. Existing PostgreSQL, Redis, Chroma, Prometheus and Grafana named
  volumes were preserved. HEAD remains 238be49; no staging, commit, push, history edit or P18 work.

### 2026-09-08 — P17 final real acceptance and strict review

- User had already verified LiteAPI Sandbox with 4 returned/4 mapped hotels and Duffel Flights
  repeatedly. Final review independently ran the real LiteAPI gate once (1 passed; 4 mapped),
  one Duffel Flights-only smoke (70 raw offers), and exactly one real persistent mixed Qwen/SSE
  path (1 passed). No Stays request, commit, push, history change or P18 work.
- The mixed run executed Graph once with Send × 5; flight/hotel intervals overlapped. Each of
  three Planner calls received 5 flight/10 hotel candidates and selected known application IDs.
  Reviewer ran three times under the application bound. There were 16 inspected checkpoints;
  strict MessagePack and a fresh PostgreSQL connection restored the identical domain plan.
  Only the acceptance test's own fresh UUID thread checkpoints were deleted.
- SSE had one final plan_completed and correct duffel_test/liteapi_sandbox/demo sources. The run
  made one flight offer request, one hotel rates request and three Places lookups, with zero
  retries and all fallbacks off. Qwen's existing metrics reported 13,137 input and 1,601 output
  tokens. No model text or raw provider JSON was recorded in the report; no token estimates.
- Medium review fixes: (1) outbound one-way scope is now explicit in domain descriptions,
  final Markdown and UI, with no price or identity change; (2) prompt-only nationality provenance
  is backed by deterministic application validation. Only a dedicated current-message ISO code
  answer is accepted; inferred country-from-origin/locale is ignored. CN collection → JP
  correction and absence of preference-memory writes are covered offline. The paid non-conversational
  path does not use this intake guard, so no extra paid rerun was needed.
- Date review reads the domain description, P15 duration−1 derivation, inclusive DailyItinerary
  loop, old per-day hotel budgeting and provider request. Oct 12–16 remains 5 nights with checkout
  Oct 17. The clarification question now says last trip date, not return date. No silent switch to
  a conventional four-night checkout interpretation was made.
- Check hardening: smoke verifies HotelOption/sandbox source; real tests use separate markers;
  ordinary test transport blocks ungated Qwen as well as travel providers; safe acceptance tree
  checks reject header names case-insensitively. Grafana JSON/docs/checker/tests agree on exactly
  32 panels and six provenance values. These checks do not change provider HTTP semantics.
- Final checks: targeted offline 344 passed; full pytest 621 passed/16 skipped; Ruff and format
  passed (354 Python files), mypy passed 159 app files. Local Docker integration 10 passed/1 skipped.
  Frontend lint/typecheck/build passed, Vitest 60 passed in 11 files, mock browser E2E 2 passed
  and real-browser E2E 2 skipped. See P17_ACCEPTANCE_REPORT.md for exact commands and limitations.
- Duffel Stays remains optional, implemented but NOT VERIFIED: account access was not granted
  during P17 despite the user's attempts. Test/sandbox success is not production inventory or
  production readiness. Real mixed MCP, another real conversational browser path, and live Grafana
  visualization were not additionally run; they remain NOT VERIFIED in this final review.

### 2026-09-08 — P18 authentication and deployment implementation

- Git gate: initial clean `main` at committed P17 `aa5d8aa`; authorized fetch/fast-forward of
  two README-only commits reached clean baseline `31007f8`. P18 changes remain unstaged and
  uncommitted. No push, paid provisioning, booking, P19 or history rewrite.
- Source intent: replace demo client identity with authenticated users while preserving the
  established graph, strict MessagePack, provider facts, memory and POST SSE semantics. Actual
  implementation uses Auth0 React SDK 2.24.1 Universal Login/PKCE and PyJWT 2.13.0 RS256 API
  access-token verification. An application-owned async HTTP/JWKS pool avoids blocking the
  event loop with synchronous remote-key fetching. Configured issuer only, exact audience,
  bounded cache/response/keys, total deadline, cooldown and cancellation are tested offline.
- Auth0 principal uses a stable issuer/subject pseudonymous hash. Every legacy user_id is
  ignored for authorization; all four graph invoke/stream/state/history paths scope the public
  thread ID internally. Conversation and preference Store namespaces use the same verified
  user reference. Preference responses project the internal source key back to its public ID.
- Cost guard uses atomic Redis Lua fixed UTC windows: per-user intake and planning caps plus
  global daily planning AND intake caps. The additional global intake cap closes multi-account
  intake-only model spend not covered by a plan-only cap. All protected POSTs except reset are
  conservatively admitted (RAG search/mock plan included); rejected/failed attempts are not
  refunded. Limits are request counts, not monetary guarantees. Redis failure returns 503.
- Frontend uses SDK memory token caching and injected token getter for JSON/POST SSE. Account
  pointers are locally hash-scoped. Logout unmounts/aborts and clears only current local metadata;
  backend data remains. 401/403/429 never silently replay mutations. Real Auth0 login is pending.
- Production validates Auth0, HTTPS exact origins, trusted hosts, backend credentials and
  disabled docs/metrics. Headers do not buffer SSE or introduce an untested CSP. Bounded auth
  metrics include denied scoped resources without looking up another user's ownership.
- Source intent: a repeatable deployable RAG service, not runtime downloads or throwaway state.
  Official Python/uv digests are pinned; Linux Torch 2.13.0 uses the documented explicit CPU
  index, because initial Linux resolution included unnecessary CUDA packages. Existing macOS
  source remains unchanged. The same multilingual MiniLM model is prepared at revision
  `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`; runtime model loading is local-only. No model swap.
- Railway volumes are mounted at runtime, not pre-deploy time. Therefore Python start performs
  advisory-locked official LangGraph setup and add-only RAG reconciliation before Uvicorn
  serves /ready on validated PORT. It never resets Chroma, flushes Redis, drops tables or
  deletes stale vectors. A differing existing index requires manual migration review.
- Cloud configuration is one API replica/worker, separate private PostgreSQL/Redis/Chroma,
  Chroma `/data` volume, and Vercel's frontend directory. MCP cloud topology is intentionally
  not generalized. The account-side Wait for CI switch is documented; no deployment token is
  placed in the contents:read GitHub workflow. Workflow actions are pinned to verified SHAs.
- Review hardening includes a total JWKS deadline/cancel regression, closing all resources even
  if verifier.close fails, safe default image auth, and logout/token acquisition cancellation.
  Local container checker re-reads its random host port after restart, enforces a wall-clock
  readiness deadline, and checks non-killed exit plus application resource shutdown.
- Executed final offline checks: Ruff/format PASS (379 files), mypy PASS (169 app files),
  auth/deployment 93 passed; full pytest 714 passed/17 skipped. Ordinary Docker integration
  11 passed/1 skipped/719 deselected. Frontend locked npm install, lint, types and builds PASS;
  Vitest 77 passed/14 files, mock browser E2E 2 passed/2 real cases skipped. JS chunk-size warning
  remains non-blocking. No Auth0/Qwen/Duffel/LiteAPI real call was made during P18 validation.
- Final local image `fdb295bc36fc` built successfully, 796,042,548 bytes, runtime UID/GID10001.
  Local health/ready/RAG/demo Agent/restart/SIGTERM checks PASS; temporary API container removed,
  all named volumes retained. Docker credential helper stalled initially; an empty temporary
  CLI config used the existing Desktop daemon without changing saved credentials.
- Secret/artifact checks found no forbidden Git candidate artifacts or frontend credential
  matches. Three unchanged earlier negative-security test literals were inspected redacted.
  `.env` remains ignored, never printed/staged. These are bounded scans, not a security guarantee.
- Actual hosted CI, Auth0 login/two-user login, Railway/Vercel deployment, deployed HTTPS/SSE and
  cloud persistence/private exposure are **NOT VERIFIED**. See `P18_ACCEPTANCE_REPORT.md` for
  all 101 report items and `25_AUTH_AND_DEPLOYMENT.md` for exact beginner setup steps.
  **P18 implementation ready; cloud/auth configuration pending.**

### 2026-09-08 — Focused Railway bootstrap reliability follow-up

- Started clean at committed P18 `b249bb5`; no P19, commit, push, cloud deployment, secret
  inspection, private-service exposure or data-volume deletion. User-reported Railway model
  reloads/disappearing process are compatible with forceful termination, but OOM is not confirmed.
- Confirmed source path: bootstrap supplied every missing child to one upsert; the advanced
  adapter supplied all texts to one encode_document/encode invocation. The official model API
  internally defaults to batch_size=32, so this is not proof of a simultaneous 77-item tensor batch.
- Actual change: RAG_BOOTSTRAP_BATCH_SIZE defaults to 8, accepts integer 1–32, drives stable
  corpus-order missing-only writes and explicit deployment encode batch size. Runtime retrieval,
  query encoding and the P10 evaluation/indexing path retain their prior defaults. islice is used
  instead of Python3.12-only batched because the repository type-check target includes Python3.11.
- Source intent (same knowledge/index semantics) is preserved: same model/revision/dimension,
  corpus, child IDs, documents, metadata, collection and ranking logic. Offline full adapter
  comparisons match all records. One actual cached-model comparison of all 77 x 384 vectors
  passed rtol=1e-5/atol=1e-6; measured maximum absolute difference 8.568167686462402e-08.
  This is numeric equivalence evidence on this host, not cross-platform bitwise identity or a
  new P10 retrieval-quality result. No texts or vectors were printed.
- Safe flushed stages cover every boundary/batch; failures expose only phase/class. No raw
  exception message, repr, traceback, DSN, token or chunk data is logged by the new diagnostics.
- Bootstrap model/vector/corpus ownership ends in an inner coroutine before one GC pass and
  runtime creation. Cyclic weakref and actual runtime-factory tests verify the old model is gone
  before the next load. Chroma gets embedding_function=None, not the bootstrap model function.
  Native allocator RSS release is not guaranteed by GC, and a killed process cannot log cleanup.
- First ordinary integration rerun exposed two pre-existing fixtures inheriting local Auth0
  configuration (401, not a RAG error). Test-process demo auth isolation now parallels existing
  deterministic travel/LLM isolation unless RUN_AUTH0_INTEGRATION_TESTS=1 is explicit. Application
  auth behavior and production validation are unchanged.
- Local fresh-index checker uses an isolated, non-public Chroma/tmpfs and a 1 GiB/no-extra-swap API
  container, rather than reusing the already indexed local collection. It verifies 77 children,
  ten batches, continued /ready success, no reindex after restart and graceful shutdown, and
  reads the kernel memory high-water mark only if available. Existing named volumes are retained.
- `/ready`, Railway private networking and deployment topology remain unchanged. A cross-region
  private mesh is supported; additional latency is possible, but is not a diagnosed crash cause.
  Official references and exact local results are in `P18_BOOTSTRAP_FIX_REPORT.md`.
- Actual local1GiB/no-extra-swap fresh-index acceptance failed: OOMKilled=true,exit137,last
  stage embedding_load_start, before any indexing batch. A separately explicit local2GiB run
  passed77 children/10 batches,/ready,demo plan,stable probes,restart(no reindex) and graceful
  shutdown. Kernel cgroup memory.peak was1,543,884,800bytes on arm64, not a Railway/RSS metric.
  This capacity limitation remains unresolved at1GiB; Railway settings/billing were not changed.
  Current Transformers ignores legacy low_cpu_mem_usage; no ineffective flag/precision/model
  change was added. The new diagnostics make this pre-index failure visible.
- Final gates: Ruff/format passed (382 files); mypy passed (170 app files); targeted tests
  52 passed; full offline suite 754 passed/17 skipped; ordinary local integration 11 passed,
  1 skipped,759 deselected. Both isolated test runs cleaned up their containers/tmpfs; all five
  existing named volumes remain. Git diff whitespace check passed; HEAD remains b249bb5 and
  all 16 fix files are unstaged. No commit, push or Railway resource change.

### 2026-09-15 — P19 product quality and review handoff (local only)

- Continued the interrupted P19 working tree at HEAD `6bc79ba`; did not restart P00–P18,
  undo edits, stage, commit, push, deploy, restart production, or delete data. Recovery found
  the saved implementation/tests and three fixture JPGs, but the handoff documents had not
  yet been saved. No residual test/server process required termination.
- Source intent: five parallel search branches supply grounded planning facts. Actual fix:
  the route branch still runs but reports non-critical unavailability when coverage cannot
  be verified. The old seeded local-transit minutes were inappropriate for the trip's
  origin/destination. Provider, worker, Planner inputs and assembly now exclude them, even
  from legacy/injected result JSON. This is not a new route service or a geographic heuristic.
- Source intent: bounded Planner–Reviewer refinement with honest outcomes. Actual response:
  optional/default `TravelPlan.quality` and bounded warnings project existing review fields;
  they do not change thresholds, maximum rounds or execute another graph. Finalize, persistent
  HTTP/SSE results and state/history share this projection. Missing/inconsistent historical
  review remains unknown; historical route text is warned about, not rewritten.
- Frontend uses the durable summary, not a default accepted state or ephemeral review event.
  Terminal/error/stop/restore quiesce progress; late events are ignored. Old account requests
  cannot dispatch or update recent-trip metadata. Hotel inclusive-night semantics, exact
  quote totals, outbound-only flight and excluded-fee warnings remain explicit. Progress and
  final quality now both display 62.5 rather than one rounding it to 63.
- Actual offline isolation: two locally signed test JWT identities, the same public UUID,
  non-empty conversations/plans/history/preferences, spoofed user_id fields and cross-user
  deletion. A changes its draft without changing B. PostgreSQL is separately opt-in and
  localhost-only; initially not run because no project containers were running. The separately
  authorized pre-publication follow-up below subsequently executed this PostgreSQL branch.
- Browser isolation is explicitly a mock SDK fixture exercising AuthRoot/App, not Auth0 cloud
  acceptance. Fixed the Vite React module/version mismatch and kept API routing under /api/v1/,
  never /src/api/. A late response deliberately ignores AbortSignal and still cannot restore
  A's UI after switching to B. Ordinary test server settings isolate real .env.local auth and
  inherited VERCEL_ENV; production Auth0 validation itself is unchanged.
- Chroma uses current official get_collection/get/query with embedding_function=None and a
  stored vector. Count, sorted IDs, collection metadata, fixed content sample, query anchor,
  endpoint/context and configured model/revision are compared. It does not create collections,
  write records, index, use Redis as evidence, or load a SentenceTransformer. Build-corpus
  is pure fixture/ID construction, not index_advanced_corpus. See the official
  [Client](https://docs.trychroma.com/reference/python/client) and
  [Collection](https://docs.trychroma.com/reference/python/collection) references.
- API deviation: the installed synchronous Chroma HTTP client's calls cannot be forcibly
  cancelled by abandoning an async waiter. The CLI uses a 60-second signal plus an outer
  70-second subprocess supervisor that kills/reaps its own blocked worker. Offline tests
  exercise the real process deadline. This is not an exact OS scheduling/time guarantee.
  The implementation lives under app/deployment so the existing image COPY includes it;
  scripts/check_chroma_persistence.py remains the local entry. No Dockerfile/startup change.
- The helper cannot independently prove a restart/no-reindex window. Production before/after
  collection checks and Chroma-only restart remain NOT VERIFIED. Runtime location, permissions,
  commands, evidence requirements and stop conditions are in 26_PRODUCT_QUALITY_AND_HANDOFF.md.
- Artifact review identified a PEM delimiter from Auth0/JOSE parsing, not an embedded key.
  Actual rebuilt output was matched to a 97-module in-memory Vite build: no test/auth fixture
  modules, full private key, or synthetic credential markers; only the five allowed public
  VITE configuration names. Three backend redaction tests contain generated synthetic strings,
  not usable provider secrets. Changing their literal spelling is not the security evidence;
  provenance, dependency graph, rebuilt bytes and bounded scans are recorded separately.
- Selected screenshots are the actual running local app, labeled Local fixture demonstration;
  no real Auth0 identity/session was captured. Trace/HAR/login state remain ignored. No video
  was recorded; DEMO_WALKTHROUGH.md provides a 1–2 minute script. Historical credential
  revocation was initially unconfirmed; on 2026-09-15 the user explicitly confirmed all three
  old Qwen/Duffel/LiteAPI credentials revoked and replacement credentials in Railway/local use.
  Record only USER CONFIRMED and date, never values; this is not a provider-console audit.
- Final local results and exact modified-file inventory are in P19_ACCEPTANCE_REPORT.md.
  Historical P18 public results remain USER-REPORTED HISTORICAL, not fresh P19 CLOUD VERIFIED
  evidence. Publication must upgrade strict frontend consumers before the new backend fields,
  with old tabs refreshed or a short maintenance window. No P20 work is included.

### P19 pre-publication local integration follow-up — 2026-09-15

- Same HEAD 6bc79ba and existing P19 worktree retained. Explicitly local Docker Desktop
  desktop-linux/Unix socket; started only postgres/redis/chroma with --wait. All existing
  named volumes retained; saver/store idempotent setup passed. No production access or reset.
- Source intent: local integration must not silently become real-provider/cloud acceptance.
  tests/conftest.py now isolates integration settings to loopback and deterministic/demo modes,
  disables tracing/model downloads, bypasses proxies for loopback, rejects non-loopback real
  httpx transports, and leaves injected MockTransport usable. Real .env files are untouched.
- First run: 3 failed, 9 passed, 1 skipped. Failures were legacy route-success/count assertions
  in MCP/review/SSE integration. Updated to assert five tasks, four successful result branches,
  noncritical route error and explicit warning; no quality threshold or graph change.
- Added three real PostgreSQL application-reopen regressions: accepted quality, forced-finalized
  quality at the existing max rounds, and pre-P19 checkpoint defaults without rewrite. Read-only
  state/history disallow graph execution; strict MessagePack/no pickle retained. Existing
  non-empty A/B same-public-UUID JWT test's PostgreSQL branch now participates in -m integration.
- Actual final results: integration 15 passed/1 skipped/800 deselected; offline backend
  795 passed/21 skipped; Ruff check and format (399 files), mypy (173 files) passed. The sole
  integration skip is separately gated P13 observability. Frontend quality subset 5 passed;
  full unaffected frontend/browser results remain the earlier P19 run, not a new execution.
- Rebuilt the existing Dockerfile locally. COPY app contains app.deployment.chroma_evidence;
  scripts wrapper is absent as expected, so cloud instructions use python -m. No dependency,
  Dockerfile, startup or production change. Helper help runs network-none; before/after in a
  UID 10001, 2 GiB/no-extra-swap container queried the existing local 77-record/384-dim collection.
  Model-load guard plus absent sentence_transformers/torch imports confirmed no second model.
  Ordinary image build still performs the existing pinned-model preparation; the builder itself
  was not capped to 2 GiB. Helper container removed, hash-only baseline copied to .p19-private.
- Compatibility: actual old schema from git show 6bc79ba accepts legacy plans but rejects new
  quality/warnings in plan and final SSE (accepted and forced). Current schema accepts old
  missing fields as unknown and new fields normally. Consumers first; controlled maintenance
  and user refresh required, never promise forced automatic upgrade of all open browser tabs.
- Production two-user and Chroma-only restart checks remain NOT VERIFIED. Only local image
  packaging/runtime is verified, not current Railway module presence/SSH permissions. Exact
  CLI, private file transfer, stop conditions and final Git inventory are in the P19 report.

### P19 publication closeout — Markdown-only synchronization

- Source intent: close the completed independent AI Travel Planning Agent project milestone
  without reopening implementation or implying that every optional cloud check passed.
- Actual local evidence: clean worktree at the first synchronization; a repeat closeout request
  found and retained the same five uncommitted Markdown changes. Git log/show still identify P19 commit
  `73e993300f12439e4418d20a0e105062d65eaabe`, message
  `fix: clarify itinerary quality and finalize acceptance checks`, with 74 changed files.
  `6bc79ba` is the historical pre-P19 README baseline, not the P19 feature commit. Local
  origin/main agrees with HEAD but no fetch/platform query establishes deployed revisions.
- Publication source: the owner reports “好了都搞定了，现在更新 md 吧。” Frontend and backend
  publication are USER-REPORTED COMPLETE at the overall release level. No cloud deployment
  IDs, exact publication times, running SHAs, fresh hosted-CI result or restored Railway
  autodeploy switch are inferred. The handoff order was frontend, old-tab refresh, backend;
  this is not a claim that every open browser tab was forcibly upgraded or independently checked.
- Verification records retained, not rerun or summed: P19 implementation frontend 85 tests /
  15 files and browser E2E 6 passed / 2 skipped; later pre-publication backend 795 passed /
  21 skipped, local Docker integration 15 passed / 1 observability skip, frontend quality 5
  passed, Ruff/format/mypy/diff checks passed, image build and 2 GiB local helper passed.
  Chroma evidence remains local: 77 records / 384 dimensions, matching summaries/direct query,
  no second full embedding model. No production Chroma restart is established by that result.
- No new itemized production two-user or Chroma-only restart evidence was found in the current
  conversation/reports; both remain NOT VERIFIED rather than automatically CLOUD VERIFIED.
  P18 public acceptance/hosted CI remain USER-REPORTED HISTORICAL; historical reports unchanged.
- Product wording now consistently describes five branches with unsupported route unavailable,
  not guessed minutes; workflow completion distinct from acceptance; forced drafts and unknown
  history; read-only recovery and local account-switch isolation. Duffel Developer Test,
  LiteAPI Sandbox, demo attractions/weather and no booking/live-route guarantee remain explicit.
- Historical credential revocation remains USER CONFIRMED, 2026-09-15, not an independent
  provider API revocation test. No values recorded. Three existing JPGs remain Local fixture
  demonstration; no new video evidence, so the optional ~100-second script is retained.
- This turn changes only the five allowed Markdown files and checks their diff, local links,
  image paths, milestones and evidence labels. No code/test/CI/Dockerfile edits, application
  test reruns, network verification, paid calls, service restart, commit, push, tag or release.
  Maintenance and optional improvements do not automatically open P20 or another phase.

### 2026-09-16 — Post-P19 frontend CI account-switch fixture regression

- Scope: started with a clean worktree at `76f85a7`, after the P19 documentation commit.
  This is a focused test-fixture repair, not a restarted phase or a backend/auth change.
  The owner reported two GitHub Actions failures, before the account-switch assertions.
- Reproduction: after `npm ci`, both desktop-chromium and mobile-chromium failed waiting
  for `Private a hotel`. Restarting with the generated cache passed both; two further
  clean-install reproductions failed both again. The diagnostic run captured HTTP 504 for
  `/node_modules/.vite/deps/react.js`, with no page exception. This was Vite's module load,
  not an API/backend response. Increasing the assertion timeout would not repair it.
- Root cause: the inline SDK replacement manually imported a Vite optimized React file
  using the intercepted Auth0 module's `?v=` value. Cold optimization can give dependencies
  different generations/hashes; Vite rejects stale optimized imports with HTTP 504. It also
  owns CommonJS/ESM interop, so copying an internal URL/export shape is not a stable API.
  This is a reproducible cache-dependent fixture bug, not evidence of a storage-seeding
  race, real Auth0 configuration leak, or production account-isolation defect.
- Precondition trace: the fake SDK starts with `auth0|fixture-a`. Both the fixture and the
  real AuthRoot compute SHA-256 of `tenant.example` + NUL + that subject. `addInitScript`
  writes each A/B `thread-id:auth:<scope>` and `recent-threads:auth:<scope>` before navigation.
  The same public UUID is deliberate; bearer fixture identity selects each private
  conversation, whose `plan_available` triggers the mocked state GET and private hotel.
  No plan/hotel is seeded globally in localStorage. That initialization order was retained.
- Minimal fix: move the fake SDK to `frontend/tests/e2e/fixtures/auth0-sdk.ts`, served and
  transformed by Vite with a normal bare React import. The intercepted SDK only re-exports
  that module. No production application import, Vite/Playwright/CI configuration change,
  dependency change, extra retry, sleep, timeout increase, or deleted/skipped assertion.
  Keep precise `/api/v1/` and `/health` interception; now assert every API path uses the
  intended public UUID and report failed script paths/statuses without response bodies.
  Existing non-empty A/B, late-A response, scoped recent metadata and logout assertions
  remain; switching back to A and then B also restores only the matching private content.
- Environment comparison: CI declares Node 24 on Ubuntu; local verification used Node
  24.20.0/npm 11.19.0 on macOS and the unchanged lockfile, Playwright 1.62.1 with bundled
  Chromium revision 1234 (151.0.7922.34). The exact failed runner's Node patch was not supplied.
  CI uses VITE_AUTH_MODE=demo; the existing ordinary-test webServer forces demo, empty API
  base and development deployment mode. Commands additionally used fake public Auth0
  values and RUN_UI_E2E=0, never developer sessions or real cloud APIs. No .env file edited.
- Final local results: clean-install targeted run 2 passed; then repeat-each=5, workers=2,
  retries=0 passed 10 (5 per project). Full E2E passed 6 with 2 real-backend cases gated off;
  Vitest passed 85 in 15 files; lint, typecheck and production-mode build passed. A prior
  post-fix 10-pass run preceded a lint-only correction from async-without-await to explicit
  Promise returns; the final repeated run above includes that correction. The existing
  >500 kB build warning and npm installation-script warnings were not hidden or bypassed.
- Repository checks: Ruff check/format passed (399 files), mypy passed (173 app files),
  offline pytest passed 795 with 21 explicit skips. All real/infrastructure test gates
  were disabled; no Docker integration, backend server, Auth0/Qwen/Duffel/LiteAPI call,
  deployment, commit or push. No fixture SDK markers occur in the built production JS;
  this bounded check is not a full security audit. Generated browser output remains ignored.
  Hosted CI still requires the user's next authorized commit/push/run; local success is
  not a GitHub Actions rerun result.

Reproduce locally from a clean dependency install (fake public values only; do not deploy
this build). Playwright's existing webServer overrides keep the fixture server in demo mode:

```bash
cd frontend
export CI=1 RUN_UI_E2E=0 CAPTURE_P19_SCREENSHOTS=0 CAPTURE_UI_SCREENSHOTS=0
export VITE_AUTH_MODE=auth0 VITE_AUTH0_DOMAIN=tenant.example VITE_AUTH0_CLIENT_ID=fixture
export VITE_AUTH0_AUDIENCE=https://fixture.example VITE_API_BASE_URL=https://api.example VERCEL_ENV=production
npm ci
npm run test:e2e -- --grep 'mock SDK account switching clears private UI and scoped recent metadata' --project=desktop-chromium --project=mobile-chromium --repeat-each=5 --workers=2 --retries=0
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run test:e2e
cd ..
git diff --check
git status --short
```
