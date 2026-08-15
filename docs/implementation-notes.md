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
