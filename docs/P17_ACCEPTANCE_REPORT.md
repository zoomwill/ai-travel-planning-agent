# P17 continuation — acceptance and review report

Date: 2026-09-08. Scope: Duffel Flights + LiteAPI Hotels, not P18.

**Offline validation and the requested real mixed-provider acceptance have passed.**
This final continuation independently ran one gated LiteAPI Sandbox integration, one Duffel
Flights-only regression smoke, and one complete real persistent mixed Qwen/Agent/SSE test, in
that order. The earlier missing-configuration result is historical, not the current status.
No real Stays request, staging, commit, push, history change or P18 work was performed.

This report distinguishes executed results from previous user-reported verification.
It is not a production-readiness claim.

## 82 requested items

| # | Item | Implementation / actual evidence |
|---|---|---|
| 1 | Starting HEAD | `238be49`, on `main`; unchanged at handoff. |
| 2 | Initial P17 worktree | This final review started with 63 tracked modifications + 47 untracked files = 110 paths. The earlier continuation started with 50 + 28; those are historical counts, not this review's baseline. All pre-existing P17 work was preserved. |
| 3 | Existing Duffel work | Preserved, including real-schema fixes, Decimal flight mapping, all segments, full carrier names, stable identities and offline tests. No reset, stash or recreation of P00–P16. |
| 4 | Provider selection | Central `TravelProviderBundle` and lifespan runtime compose per-kind providers. Graph and MCP transport do not choose vendors independently. |
| 5 | Data modes | `demo`: all five demo; `external`: explicit flight/hotel selectors; `duffel`: legacy Flights + Stays. |
| 6 | Flight config | `TRAVEL_FLIGHT_PROVIDER=demo\|duffel`, default duffel when external mode is selected. |
| 7 | Hotel config | `TRAVEL_HOTEL_PROVIDER=demo\|liteapi\|duffel_stays`, default liteapi when external mode is selected. |
| 8 | Legacy compatibility | The legacy duffel mode still uses Stays, never silently switches to LiteAPI. The top-level default is demo. |
| 9 | httpx | Executed version check: **0.28.1**. Reused existing dependency, no hotel SDK added. |
| 10 | Official LiteAPI API | Fixed `POST https://api.liteapi.travel/v3.0/hotels/rates`; official references below. |
| 11 | Authentication | Server-side `X-API-Key` from Pydantic `SecretStr`; never a tool argument, browser field, state field or log field. |
| 12 | Trusted host | Fixed absolute HTTPS URL, constructor checks injected base URL, no configurable alternate host, redirects disabled. Fake-transport tests reject the wrong host and redirects. |
| 13 | Environment | `sandbox\|production`, default sandbox. Key-prefix validation and optional response sandbox attestation prevent known environment mismatch; no token prefix exposed in status. |
| 14 | Retry | Default one retry, allowed 0–2. Only transport/timeouts, 429, 500/502/503/504; Retry-After capped at 2 seconds. No auth/schema retry. MCP adds no external-search retry. Smoke explicitly uses zero retries. |
| 15 | Timeout | HTTP timeout default 20 seconds, >0 and ≤60. Vendor request timeout 6 seconds. MCP deadline accounts for both location/provider timeout and retry budgets. Cancellation propagates. |
| 16 | Errors | Bounded `liteapi_*` codes: configuration, authentication, rate-limit, timeout, transport, schema/response, empty rates, invalid nationality, unsupported request, provider failure. Schema logs contain only provider, operation, count, loc and type. |
| 17 | Shared location | Duffel Places supplies official city/IATA/coordinates, not Qwen or a private city table. LiteAPI prefers coordinates plus 10 km radius, otherwise official IATA. Only LiteAPI opts into coordinate-optional resolution; legacy Duffel default is preserved. LiteAPI still needs the Duffel location credential even with demo flights. |
| 18 | Nationality model | Optional explicitly supplied assigned ISO alpha-2 code, normalized uppercase. Invalid/unassigned values fail; no origin/IP/language/browser inference. |
| 19 | P15 intake | Deterministic missing-field/confirmation checks require nationality for LiteAPI. A new current-message guard accepts a dedicated ISO-code answer, not model inference from origin/locale or negated text. Offline tests cover collection, correction and rejected inference. Direct, persistent non-stream and SSE endpoints reject missing nationality before graph execution. |
| 20 | Long-term memory | Nationality is trip-specific, not automatically saved as a preference. CN collection → JP correction leaves the preference store empty in the regression. Explicit trip data can exist in thread checkpoints; it is not claimed to be absent from short-term state. |
| 21 | Hotel request | checkin, exclusive checkout, currency, guestNationality, one occupancy for 1–2 adults, coordinates/radius or IATA, includeHotelData, roomMapping, limit, maxRatesPerHotel, timeout and stream=false. |
| 22 | Result cap | LiteAPI hotels default 10, range 1–20; rates/property default 1, range 1–20. Application caps before State/LLM/SSE, not just by trusting the vendor limit. Explicit fallback and MCP also obey caps. |
| 23 | Offer selection | One-room offer, exactly one compatible rate total, matching currency, matching adult/child counts if provided, offer total agrees with rate total if present. Cheapest valid exact total per property, deterministic property-ID tie-break; duplicate property quotes compare exact totals. |
| 24 | Total price | JSON numeric money parsed directly as Decimal; exact `total_stay_price` preserved. Planning budget uses this total, not a reconstructed rounded total. |
| 25 | Nightly price | Exact total / nights, rounded to cents using ROUND_HALF_UP, explicitly an average. Domain rejects inconsistent total/night/average combinations. |
| 26 | Dates | Code review confirms the domain's last-calendar-date description, P15 end=start+duration−1 derivation and the planner's inclusive loop. The intake question now says last trip date, not return date. No project-wide semantic change. See the cross-layer proof below. |
| 27 | Nights | Existing per-day hotel budgeting means Oct 12–16 = 5 days / 5 nights / checkout Oct 17. Cross-layer regression covers intake, requirements, itinerary, request and exact cost. Zero nights rejected. This is a project convention, not a universal travel convention. |
| 28 | Included fees | Already included in the selected total; never added twice. |
| 29 | Excluded fees | Any included=false disclosure sets `has_excluded_fees`; UI and markdown warn of additional property-payable fees. Missing fee metadata is not advertised as a guaranteed all-in price. |
| 30 | Ratings | Nullable property stars (0–5) and guest review score (0–10) remain distinct. Missing values are not invented. |
| 31 | Amenities | Only provider-supplied bounded strings; missing/null becomes an empty list. No fabricated Wi-Fi/breakfast. |
| 32 | Distance | Haversine only when hotel and destination coordinates both exist; otherwise null, never guessed. |
| 33 | Provenance | Fixed values: demo, demo_fallback, duffel_test, duffel_live, liteapi_sandbox, liteapi_production. Carried by domain, summaries, MCP, checkpoints, SSE and UI. |
| 34 | Duffel Flights | Existing HTTP request/mapping path preserved. This review's single Flights-only smoke passed with 70 raw offers; earlier user runs are separate historical evidence. Flight price and selection are explicitly outbound one-way, with return flight excluded in domain documentation, Markdown and UI. |
| 35 | Duffel cap | Default 5, configurable 1–20, before State. Fake 81-offer regression remains. The real mixed run had 5 flight candidates in all three Planner inputs, and candidate caps were checked across all 16 checkpoint snapshots. |
| 36 | Duffel Stays | Retained as optional selectable adapter. Coordinate requirement preserved; no booking functionality added. |
| 37 | Stays verification | **NOT VERIFIED**; account access was not granted during P17 despite the user's attempts. Optional and not a completion gate. No real Stays call this continuation. |
| 38 | Fallback | Off by default. Explicit opt-in only, logged/labeled demo_fallback and capped. Provider failure is not silently turned into demo success. |
| 39 | Direct backend | One lifespan-owned pool/provider; both pools closed even if one cleanup fails. Offline mixed tests and the complete real direct mixed Agent/SSE path passed. |
| 40 | MCP backend | Independent server process builds the same provider selection and owns its clients; JSON domain DTOs only, bounded source validation/caps, nationality round-trip, no key in tool arguments. Fake mixed-provider MCP parity and local deterministic MCP integration passed. Real mixed-provider MCP deployment: **NOT VERIFIED**. |
| 41 | Status API | Local-only per-kind provider/environment/configured/fallback data plus location dependency. Mixed mode has no misleading single global environment. No searches to discover provider availability. |
| 42 | Readiness | Local selected credential presence plus existing infra checks. Missing required key -> /ready 503, /health 200. Status/readiness do not call hotel/flight search. Key validity or account access is not claimed from presence alone. |
| 43 | MessagePack | The real mixed run inspected 16 PostgreSQL checkpoints and restored the identical internal domain plan through a fresh connection using the strict serializer. Safety checks reject raw fields, credentials and runtime objects. Only the fresh acceptance UUID's checkpoints were cleaned; no permissive serializer change or volume deletion. |
| 44 | Qwen grounding | Three real Planner calls each received 5 flights/10 hotels and returned known application candidate IDs; existing full grounding remained active. Unknown/duplicate-ID and identity stability offline regressions passed. Raw provider payloads are not model input. |
| 45 | Reviewer | Existing round limit retained. The real run made 3 Planner and 3 Reviewer calls, with retries and fallback off. This proves bounded execution, not a claimed quality score or production suitability. |
| 46 | SSE | One actual graph.astream invocation, Send × 5, overlapping external flight/hotel searches and no fixed completion order. Real assertions passed for one run_started, monotonic sequence, safe mixed sources and exactly one final plan_completed. Public terminal projection clears volatile IDs using a copy. No graph rerun, token streaming or replay added. |
| 47 | Metrics | Bounded provider/operation/status and kind/source/status labels; no nationality value, location, candidate ID, price, key or user labels. Actual mixed-run counts: 3 Duffel Places lookups, 1 flight offer request, 1 LiteAPI rates request. Qwen provider-reported tokens: 13,137 input / 1,601 output. |
| 48 | Grafana | JSON, docs, checker and tests agree on exactly 32 panels and six provenance values. Regression rejects both 31 and 33 panels. Live dashboard visualization/scrape acceptance: **NOT VERIFIED**. Remote MCP HTTP-attempt metrics are not exported by the API registry; API tool/source metrics remain available. |
| 49 | Source badges | Frontend validates and renders Duffel test/live, LiteAPI sandbox/production, demo and explicit fallback. Desktop/mobile fake mixed journey passed. |
| 50 | Fee warning | Hotel total, average/night, room/board/refundability and additional-property-fee warning rendered. Nullable values stay honest. Unit/browser tests passed. |
| 51 | Booking UI | No booking/payment/reservation flow. E2E asserts no booking/reserve/pay/checkout button. |
| 52 | Targeted tests | **344 passed**: external, LLM, MCP, streaming, intake, observability and dashboard-checker tests. Exact command below. |
| 53 | Ruff | `uv run ruff check .`: **PASS** after fixing formatting/line-length issues found during implementation. |
| 54 | Format | `uv run ruff format .` executed; final `--check`: **354 files already formatted**. |
| 55 | mypy | `uv run mypy app`: **PASS**, 159 application files. |
| 56 | Full pytest | **621 passed, 16 skipped**. Real API gates off. Ordinary tests also block ungated Qwen network access. |
| 57 | Integration | `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q`: **10 passed, 1 skipped, 626 deselected**. Deterministic local infrastructure/MCP checks; no real travel or Qwen request. |
| 58 | Frontend lint | `npm run lint`: **PASS**. |
| 59 | Frontend types | `npm run typecheck`: **PASS**. |
| 60 | Vitest | `npm run test:run`: **60 passed**, 11 files. |
| 61 | Frontend build | `npm run build`: **PASS**. Not a performance benchmark or deployment claim. |
| 62 | Frontend E2E | `npm run test:e2e`: **2 passed** (desktop/mobile mocked mixed journey), **2 skipped** (gated real backend). Only non-fatal NO_COLOR/FORCE_COLOR warnings. |
| 63 | Real LiteAPI integration | Exactly one `liteapi_integration` run: **1 passed, 628 deselected**, exit 0, zero retries. Revalidates mapped HotelOption and sandbox source; emits safe summary only. |
| 64 | Real hotel count | Isolated LiteAPI gate: **4 returned / 4 mapped**, source liteapi_sandbox. Complete mixed run: **10 bounded hotel candidates** in each Planner input; that is not a claim about its raw response count. |
| 65 | Real Duffel regression | Exactly one Flights-only checker invocation after the hotel gate: **PASS, 70 offers**, test environment, zero retries. No Stays flag or call. |
| 66 | Real mixed Agent/SSE | Exactly one external_agent_integration run: **1 passed, 628 deselected**. external/direct + Duffel Test + LiteAPI Sandbox + three demo providers; all fallbacks/retries off, actual PostgreSQL/RAG/Qwen, one graph execution. |
| 67 | Real Qwen | One complete Agent path, not one model request: **3 Planner + 3 Reviewer calls**. Metrics reported **13,137 input / 1,601 output tokens**; no estimated costs, prompt text or completion text recorded. |
| 68 | Secret scan | Generic key-pattern scan found only five synthetic security/transport test fixtures; their contexts were inspected with matched values redacted. No match in app/scripts/frontend source or build/docs/template. No real key or raw response was printed or persisted. Pattern scanning is not an absolute secret-detection guarantee. |
| 69 | .env | `git check-ignore -q .env` exit 0. Never directly inspected, printed or edited real .env contents. Smoke used normal application Settings loading, with values hidden. Index/worktree artifact-name audit found only .env.example. No files staged. |
| 70 | Booking endpoint audit | No matches for air/orders, rates/prebook, rates/book, stays/bookings or payments in app/scripts/frontend source. Reviewed clients expose search-only operations. |
| 71 | Port 5173 | Final lsof: no listener. Temporary Playwright/Vite server stopped. |
| 72 | Port 8000 | Final lsof: no listener. No temporary FastAPI server remains. |
| 73 | Port 9001 | Final lsof: no listener; project MCP HTTP/STDIO pgrep found no process after integrations completed. |
| 74 | Docker | PostgreSQL and Redis running/healthy; Chroma running. Independent check: PostgreSQL accepting connections, Redis PONG, Chroma HTTP 200 with executor and log client ready. |
| 75 | Volumes | All 5 preserved: postgres_data, redis_data, chroma_data, prometheus_data, grafana_data, with project prefix. No down -v or volume removal. |
| 76 | Git | Final worktree: **63 tracked modifications + 50 untracked files = 113 paths**. Three new acceptance-test files added during this final review; all previous P17 work retained. No staged files, commit/push/history edit. Normal git diff --stat excludes untracked files. Full manifest below. |
| 77 | Critical findings | No unresolved Critical issue identified in the scoped review. This is not an absolute security guarantee. |
| 78 | High findings | No unresolved High issue identified in the scoped review. |
| 79 | Medium findings | Final review fixed ambiguous one-way scope and prompt-only nationality provenance, with regressions. Earlier fixes retained: persistent preflight, exact-total duplicate quote choice, reachable IATA fallback, fallback cap. No unresolved Medium issue identified within scope. |
| 80 | Limitations | Test/sandbox, not production/bookable inventory; outbound one-way only; 1 room/1–2 adults; no FX; three demo categories. Nationality intake requires a dedicated ISO-code reply, not inferred prose. Real mixed MCP, real browser/conversational flow after the intake guard, and live Grafana remain **NOT VERIFIED**. Optional Stays lacks account access. Inclusive nights and separately payable fees remain explicitly disclosed. |
| 81 | P18 | **Not entered.** No authentication/deployment scope added. |
| 82 | Suggested commit | `feat: integrate multi-provider travel search` — suggestion only, **not executed**. |

## Actual safe outputs

LiteAPI gated integration (one invocation, one rates request, zero retries):

```text
PASS LiteAPI environment: sandbox
PASS Hotel rates access
PASS Hotels returned: 4
PASS Mapped hotel candidates: 4
PASS Hotel domain/source: liteapi_sandbox
1 passed, 628 deselected in 1.30s
```

Duffel Flights-only regression (one invocation, no Stays):

```text
PASS Duffel environment: test
PASS Flights access
PASS Flight offers: 70
```

One complete real persistent Agent/SSE acceptance:

```text
PASS Mixed sources: flights=duffel_test hotels=liteapi_sandbox attractions=demo weather=demo route=demo
PASS Graph/SSE: one execution, Send x 5, concurrent external branches, one terminal plan_completed
PASS Grounded Qwen: planner_calls=3 reviewer_calls=3 candidate_counts=[(5, 10), (5, 10), (5, 10)]
PASS RAG and strict checkpoint history: checkpoints=16
INFO Provider-reported Qwen tokens: input=13137
INFO Provider-reported Qwen tokens: output=1601
INFO External request count: provider=duffel operation=location_lookup status=success count=3
INFO External request count: provider=duffel operation=flight_offer_request status=success count=1
INFO External request count: provider=liteapi operation=hotel_rates status=success count=1
PASS Fresh PostgreSQL connection restored identical plan; test-only checkpoint cleaned
1 passed, 628 deselected in 48.12s
```

The real gates ran before eight final nationality regressions were added. Their actual
`628 deselected` output is preserved rather than recomputed. Final offline results include
the nationality guard. The real non-conversational path does not use that guard; no additional
paid rerun was necessary. Durations above are command output, not performance benchmarks.

Infrastructure:

```text
PASS PostgreSQL: /var/run/postgresql:5432 - accepting connections
PASS Redis: PONG
PASS Chroma: HTTP 200: {"is_executor_ready":true,"is_log_client_ready":true}
```

Final Docker service summary from compose ps:

| Service | Image | Status | Local binding |
|---|---|---|---|
| postgres | postgres:16.14-alpine | running (healthy) | 127.0.0.1:5432 |
| redis | redis:7.4.9-alpine | running (healthy) | 127.0.0.1:6379 |
| chroma | chromadb/chroma:1.5.9 | running; HTTP readiness independently passed | 127.0.0.1:8001 |

Named volumes:

```text
ai_travel_planner_codex_pack_chroma_data
ai_travel_planner_codex_pack_grafana_data
ai_travel_planner_codex_pack_postgres_data
ai_travel_planner_codex_pack_prometheus_data
ai_travel_planner_codex_pack_redis_data
```

## Strict review findings

- **Critical:** none identified in this scoped review.
- **High:** none identified in this scoped review.
- **Medium — fixed:** an outbound-only quote could look like a complete return itinerary.
  Domain field descriptions, final Markdown, UI and README now explicitly state one-way and
  return-flight exclusion; backend/frontend regressions passed. Prices and candidate IDs did
  not change.
- **Medium — fixed:** nationality non-inference depended on extraction instructions alone.
  A deterministic current-message guard now ignores a model-supplied code unless the user
  supplies a dedicated code reply. Tests cover CN collection, JP correction, origin/locale
  non-inference, negation, and no preference-memory write. Multi-field or country-name prose
  may require a separate ISO-code reply; this deliberate limitation is documented.
- **Validation hardening:** exactly 32 dashboard panels; smoke domain/source assertions;
  separate real-test gates; rejection of sensitive header names regardless of case; explicit
  network blocking for ordinary Qwen tests. An initial acceptance-helper case-sensitivity
  error was caught by its negative unit test and fixed before real acceptance.

The earlier continuation's four Medium fixes (persistent preflight, duplicate exact totals,
IATA fallback, fallback caps) and existing provider behavior remain covered by passing tests.
No unresolved Critical/High/Medium issue was identified; this is not a universal security or
production-readiness guarantee.

## Cross-layer date and money proof

| Layer | Actual contract/code |
|---|---|
| `app/domain/models.py` | `end_date` is the last calendar date of the trip. |
| `app/intake/logic.py` | Duration derives `end_date = start_date + duration_days - 1`; clarification says last trip date. |
| `app/services/planning_service.py` | Inclusive day count `(end_date - start_date).days + 1`; one DailyItinerary per day; existing budgeting uses a hotel night per inclusive day. |
| `app/external/liteapi/hotels.py` | `checkin = start_date`, exclusive `checkout = end_date + 1 day`; `stay_night_count = checkout - checkin`. |
| Cross-layer regression | Oct 12–16 produces five itinerary days, five nights, and Oct 17 checkout. No silent switch to four nights. |
| Exact quote and budget | A 501.01 total over five nights displays average 100.20 (ROUND_HALF_UP), but budget uses 501.01, not reconstructed 501.00. |

Included fees are not added twice. Explicitly excluded property-payable fees trigger a warning;
missing fee data does not establish an all-in price. This date convention is project-specific,
and neither it nor the one-way flight price promises a conventional round-trip booking.

## Verification commands

Run from the project root. These first commands do not call real travel suppliers:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest tests/external tests/llm tests/mcp_tools tests/streaming tests/intake tests/observability tests/test_check_observability.py -q
uv run pytest -q
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
uv run python scripts/check_infra.py
docker compose ps
docker volume ls --filter label=com.docker.compose.project=ai_travel_planner_codex_pack
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff --name-status
git diff --cached --name-only
git check-ignore -q .env
```

Frontend, from its directory:

```bash
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run test:e2e
```

The following cost-bearing commands were already executed once each, in this order. They are
recorded for reproducibility, **not a request to run them again**. Credentials were loaded by
normal application Settings without inspecting or printing `.env`:

```bash
RUN_LITEAPI_INTEGRATION_TESTS=1 uv run pytest -m liteapi_integration -q
TRAVEL_DATA_MODE=external TRAVEL_FLIGHT_PROVIDER=duffel DUFFEL_ENV=test uv run python scripts/check_duffel.py
RUN_EXTERNAL_AGENT_INTEGRATION_TESTS=1 RUN_DUFFEL_INTEGRATION_TESTS=1 RUN_LITEAPI_INTEGRATION_TESTS=1 RUN_LLM_INTEGRATION_TESTS=1 HF_HUB_OFFLINE=1 uv run pytest -m external_agent_integration -q
```

No additional real acceptance was attempted. The explicit mixed test selects external/direct,
Duffel Test and LiteAPI Sandbox, Qwen, all fallbacks off and zero retries. The trip's US nationality
is explicit fixture input, not an inferred or production default. Existing RAG/index and real
PostgreSQL were used; only the test's own fresh UUID checkpoint was cleaned. No user conversation
or named volume was removed. One complete path can contain multiple bounded Planner/Reviewer
model requests, as the actual output above shows.

## Official references and deviations

- [LiteAPI v3 hotel rates](https://docs.liteapi.travel/reference/post_hotels-rates)
- [Authentication](https://docs.liteapi.travel/reference/authentication)
- [Rate request parameters](https://docs.liteapi.travel/docs/rate-request-parameters-guide)
- [Hotel rate price structure](https://docs.liteapi.travel/docs/hotel-rates-api-json-data-structure)
- [Official application example and response envelope](https://docs.liteapi.travel/reference/prompt-for-vibe-coding-tools)
- [Hotel display details](https://docs.liteapi.travel/docs/displaying-hotel-details)

The documentation-guided implementation uses top-level hotels metadata joined to data rates,
tolerates unused vendor fields, preserves exact Decimal totals, and follows the existing project's
date contract rather than assuming end_date means checkout. Details are in
[the provider guide](24_EXTERNAL_TRAVEL_DATA.md) and [implementation notes](implementation-notes.md).
The previous untracked Duffel guide was renamed and retained as a legacy section in the
multi-provider guide, not silently discarded.

## Final repository manifest

M means a previously tracked file has an unstaged modification; ?? means an untracked file.
This includes preserved pre-existing P17 work, not 113 newly created files in this continuation.

```text
 M .env.example
 M README.md
 M app/api/routes/agent_plans.py
 M app/api/routes/conversation.py
 M app/api/routes/persistence.py
 M app/api/routes/readiness.py
 M app/core/config.py
 M app/core/lifespan.py
 M app/core/resources.py
 M app/domain/__init__.py
 M app/domain/models.py
 M app/graphs/nodes/aggregate_search_results.py
 M app/graphs/nodes/planner.py
 M app/graphs/nodes/search_worker.py
 M app/intake/logic.py
 M app/intake/models.py
 M app/intake/service.py
 M app/llm/fake.py
 M app/llm/grounding.py
 M app/llm/models.py
 M app/llm/prompts.py
 M app/llm/reviewer.py
 M app/main.py
 M app/mcp_tools/backend.py
 M app/mcp_tools/client.py
 M app/mcp_tools/errors.py
 M app/mcp_tools/models.py
 M app/mcp_tools/servers/travel_http.py
 M app/observability/instrumentation.py
 M app/observability/logging.py
 M app/observability/metrics.py
 M app/schemas/readiness.py
 M app/search/backend.py
 M app/search/models.py
 M app/services/planning_service.py
 M app/streaming/mapper.py
 M app/streaming/service.py
 M docs/20_OBSERVABILITY.md
 M docs/implementation-notes.md
 M frontend/src/api/schemas.ts
 M frontend/src/components/itinerary/ItineraryView.test.tsx
 M frontend/src/components/itinerary/ItineraryView.tsx
 M frontend/src/components/trip/TripDraftPanel.test.tsx
 M frontend/src/components/trip/TripDraftPanel.tsx
 M frontend/src/hooks/useConversation.test.tsx
 M frontend/src/styles.css
 M frontend/src/test/fixtures.ts
 M frontend/tests/e2e/mock-journey.spec.ts
 M observability/grafana/dashboards/travel-planner-overview.json
 M pyproject.toml
 M scripts/check_observability.py
 M tests/api/test_persistence.py
 M tests/conftest.py
 M tests/domain/test_models.py
 M tests/intake/test_api.py
 M tests/integration/test_mcp_integration.py
 M tests/integration/test_streaming_integration.py
 M tests/mcp_tools/test_backend_graph.py
 M tests/mcp_tools/test_models.py
 M tests/mcp_tools/test_servers.py
 M tests/search/test_nodes.py
 M tests/search/test_parallel_graph.py
 M tests/test_check_observability.py
?? app/api/routes/travel_data.py
?? app/domain/countries.py
?? app/external/__init__.py
?? app/external/backend.py
?? app/external/duffel/__init__.py
?? app/external/duffel/backend.py
?? app/external/duffel/client.py
?? app/external/duffel/diagnostics.py
?? app/external/duffel/errors.py
?? app/external/duffel/flights.py
?? app/external/duffel/locations.py
?? app/external/duffel/mapper.py
?? app/external/duffel/models.py
?? app/external/duffel/runtime.py
?? app/external/duffel/stays.py
?? app/external/duffel/validation.py
?? app/external/liteapi/__init__.py
?? app/external/liteapi/client.py
?? app/external/liteapi/errors.py
?? app/external/liteapi/hotels.py
?? app/external/liteapi/models.py
?? app/external/liteapi/validation.py
?? app/external/locations.py
?? app/external/runtime.py
?? docs/24_EXTERNAL_TRAVEL_DATA.md
?? scripts/check_duffel.py
?? scripts/check_liteapi.py
?? tests/external/__init__.py
?? tests/external/acceptance_checks.py
?? tests/external/test_acceptance_checks.py
?? tests/external/duffel/__init__.py
?? tests/external/duffel/helpers.py
?? tests/external/duffel/test_api.py
?? tests/external/duffel/test_backend.py
?? tests/external/duffel/test_client.py
?? tests/external/duffel/test_flights.py
?? tests/external/duffel/test_locations.py
?? tests/external/duffel/test_stays.py
?? tests/external/duffel/test_validation.py
?? tests/external/liteapi/__init__.py
?? tests/external/liteapi/helpers.py
?? tests/external/liteapi/test_client.py
?? tests/external/liteapi/test_hotels.py
?? tests/external/liteapi/test_runtime.py
?? tests/external/liteapi/test_smoke.py
?? tests/integration/test_duffel_integration.py
?? tests/integration/test_external_agent_integration.py
?? tests/integration/test_liteapi_integration.py
?? tests/observability/test_external_metrics.py
?? docs/P17_ACCEPTANCE_REPORT.md
```
