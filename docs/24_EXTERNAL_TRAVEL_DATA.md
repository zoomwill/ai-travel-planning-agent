# Phase P17 — Multi-provider external travel data

P17 adds Duffel Flights + LiteAPI Hotels while preserving P16's
conversation, graph, review, persistence, SSE, and browser workflow. The default remains fully
offline deterministic demo data.

## Current provider selection

`TRAVEL_DATA_MODE=demo` forces all five branches to demo. `external` uses
`TRAVEL_FLIGHT_PROVIDER=demo|duffel` (default duffel) and
`TRAVEL_HOTEL_PROVIDER=demo|liteapi|duffel_stays` (default liteapi). The other three branches stay
demo. Legacy `duffel` still means Flights + Stays; it never silently becomes LiteAPI.
`TRAVEL_SEARCH_BACKEND_MODE=direct|mcp` is independent. Selection occurs centrally in
`TravelProviderBundle`, preserving five concurrent LangGraph Send branches.

## LiteAPI / Nuitee Connect hotel rates

Official [rates API](https://docs.liteapi.travel/reference/post_hotels-rates):
`POST https://api.liteapi.travel/v3.0/hotels/rates`, with server-side
[`X-API-Key`](https://docs.liteapi.travel/reference/authentication). No arbitrary host is
configurable. Redirects are disabled. Existing httpx 0.28.1 supplies async HTTP and MockTransport;
no vendor SDK is added. Keys remain private SecretStr configuration.

`LITEAPI_ENV=sandbox|production` defaults sandbox. Defaults/ranges: timeout 20 seconds (>0–60),
retries 1 (0–2), hotels 10 (1–20), rates/property 1 (1–20), demo fallback false. One pool/provider
is owned by each process lifespan. The independent MCP HTTP process initializes its own bundle.
Its call deadline accounts for provider timeouts/retries, with no extra external-search retry layer.

The shared authoritative resolver uses Duffel Places, including LiteAPI with demo flights, so
that configuration still requires a Duffel token for location resolution. No LLM guesses cities,
IATA or coordinates. Hotel searches prefer available coordinates (10 km radius), then use the
provider-returned IATA code if coordinates are absent. Only LiteAPI opts into coordinate-optional
resolution; legacy Duffel resolution remains coordinate-required by default.

### Explicit nationality and dates

`guest_nationality` is optional for old demo/legacy requests, but required before LiteAPI planning.
The domain accepts explicit assigned ISO alpha-2 codes, normalizing lowercase. It never derives
nationality from origin, browser, IP, user ID or language. P15 extracts an incremental patch;
application-controlled missing-field policy asks for nationality before explicit confirmation.
This field is trip-specific, not automatically written to long-term preference memory or logs.
An application-side guard accepts a new/corrected code only in an unambiguous current-message
answer: for example `CN`, `nationality: CN` or `国籍：CN`. An extractor that borrows US from an
origin/locale is ignored even if its output passes schema validation. Ambiguous or multi-field
natural language requires a separate explicit code reply; country-name inference is not added.

P03 defines end_date as the final trip day. P15 computes end = start + duration − 1. P04 emits
one DailyItinerary per inclusive day and budgets one hotel night per day. P07 preserves the same
requirements. Thus **Oct 12–16 means five days and five nights, checkout Oct 17** in this project.
This is not a universal convention. A cross-layer test connects intake, domain, daily itinerary,
provider checkout, night count and exact cost. Zero nights is rejected.

### Request, response and price contract

The [request guide](https://docs.liteapi.travel/docs/rate-request-parameters-guide) confirms
occupancies, currency, guestNationality, checkin, checkout and a location selector. We request one
room (1–2 adults), roomMapping, includeHotelData, limit, maxRatesPerHotel, six-second vendor timeout
and non-streamed JSON. Unsupported party sizes fail rather than show a misleading price.

The [official response example](https://docs.liteapi.travel/reference/prompt-for-vibe-coding-tools)
joins `data[].hotelId` prices with top-level `hotels[].id` details. Consumed fields are typed;
unused additions are ignored. One-room offers must have one rate; its currency must match the
trip, and its total must agree with any offer-level total. Choose the cheapest valid offer per
property, then cheapest properties with stable-ID tie-breaks, and cap before returning domain data.
Duplicate property entries are compared by exact total, not their rounded nightly average.
Explicit demo fallback also respects the selected external provider's candidate cap.
No raw provider JSON or offer/rate IDs enter hotel domain results or grounded candidate identity.

Parse JSON numeric amounts directly into Decimal. Keep exact `total_stay_price`; display average
`price_per_night = total / nights`, rounded to cents with ROUND_HALF_UP. Planning totals use the
exact stay quote, not a rounded average multiplied back up. No invented FX conversions.
The [price structure guide](https://docs.liteapi.travel/docs/hotel-rates-api-json-data-structure)
distinguishes included fees from separately payable property fees. Included fees are not added
twice. Any `included=false` sets a bounded `has_excluded_fees` flag; the UI warns that additional
fees may be payable at the hotel. Null fee lists are accepted. Do not call the quote all-in.

Property stars and guest review /10 are distinct nullable fields. Missing amenities remain empty.
Haversine distance is derived only with both coordinate pairs; otherwise null. Room/board names,
refundability and fee disclosure are bounded public data. No booking or payment UI exists.

### Errors and verification

Safe `liteapi_*` codes cover missing config, auth, rate limit, timeout, transport, invalid response,
no rates, invalid nationality, unsupported request and provider failure. Retry only transient
transport/timeouts, 429 and 500/502/503/504; never 400/401/403, schema or local validation failures.
Retry-After is capped at two seconds. Cancellation propagates. Default fallback stays off;
explicit fallback is labeled `demo_fallback` in State, SSE, UI, metrics and logs.

The local status API reports per-kind provider/environment/configured/fallback fields and the
location dependency, without token prefixes or remote requests. Missing credentials cause /ready
503, while /health stays 200. Missing nationality causes HTTP 422 before both non-stream and
streamed persistent graph execution. Failures after SSE
starts become safe error events. Final SSE strips volatile offer/search IDs and still executes
the graph once. Strict checkpoints retain only domain data and bounded provenance.

Sources additionally include `liteapi_sandbox` and `liteapi_production`. Sandbox is never labeled
production inventory. The existing 32-panel dashboard supports both providers; no second dashboard.
Only bounded provider/operation/status and kind/source/status labels are used, not nationality,
IDs, prices, cities, users or credentials. Direct mode's HTTP calls use the app metrics registry;
remote MCP calls retain API-side tool/source metrics, not the remote process's HTTP metrics.

Ordinary tests and Docker integration stay offline from external providers. Explicit smoke:

```bash
RUN_LITEAPI_INTEGRATION_TESTS=1 uv run python scripts/check_liteapi.py
```

The checker uses future dates, explicit NYC/US fixture inputs, at most five properties, one rate
per property, no retry, validates real schema and maps domain hotels. No rates means failure.
Diagnostics print only stable codes/counts and schema loc/type, never payloads or keys.

### Final executed acceptance on 2026-09-08

- Targeted offline regressions: **344 passed**; full Python suite: **621 passed, 16 skipped**.
- Ruff lint/format and mypy passed; local Docker integrations: **10 passed, 1 skipped**.
- Frontend lint/typecheck/build passed; Vitest **60 passed**; mock desktop/mobile E2E
  **2 passed**, real-backend E2E **2 skipped**.
- User's earlier LiteAPI smoke returned 4 hotels and mapped 4. This final review then ran the
  real `liteapi_integration` gate once: **1 passed**, 4 hotels mapped, sandbox source verified.
- One Duffel Flights-only regression passed with **70 raw offers**. No Stays request was made.
- One real persistent mixed Qwen/SSE run passed: five concurrent Send branches, one Graph run,
  one final plan_completed, 5 flight/10 hotel candidates per Planner call, 16 safe checkpoints,
  fresh PostgreSQL connection restore, and exact expected mixed provenance. Test-only thread
  checkpoints were cleaned. Planner/Reviewer each ran 3 times under the application limit.
- Existing metrics reported Qwen input **13,137** / output **1,601** tokens, not estimates.
  The full path made one flight offer request, one hotel rates request and three Places lookups;
  all retries and fallbacks were disabled. No raw provider response or key was printed or saved.
- PostgreSQL/Redis healthy, Chroma independently ready, all five named volumes preserved.

See [the full acceptance report](P17_ACCEPTANCE_REPORT.md). Real MCP transport, real browser
conversation after the new nationality guard, and live Grafana visualization were not additionally
run: **NOT VERIFIED** here. Their deterministic/offline compatibility tests passed.
Never paste credentials into chat or commit `.env`; do not repeat paid gates for routine checks.

## Legacy Duffel adapter details

When `TRAVEL_DATA_MODE=duffel`:

- Flights uses `POST https://api.duffel.com/air/offer_requests`.
- Hotels uses `POST https://api.duffel.com/stays/search`.
- Places uses `GET https://api.duffel.com/places/suggestions` for official city/IATA/coordinates.
- Attractions, weather, and routes still use deterministic demo providers.

P17 is search-only. It does not create air orders, fetch booking quotes, create stays bookings,
reserve inventory, collect payment, or claim that an offer is bookable.

## Developer Test Mode and live mode

Duffel test and live environments use different access tokens on the same fixed HTTPS host. The
configuration—not automatic token inspection—selects `DUFFEL_ENV=test|live`. A consistency check
rejects an obviously mismatched test token, but a prefix is not treated as authentication proof.

Test mode proves real Duffel API transport and mapping. Duffel's test flight prices are not live
production prices, so the API, checkpoint, SSE, and UI all label them `duffel_test`, and the browser
shows “Duffel Test · Test data.” Stays requires separate account access. A successful Flights test
does not imply Stays access or full P17 real acceptance.

## Configuration and secrets

Copy `.env.example` to the ignored `.env`, then set:

```dotenv
TRAVEL_DATA_MODE=duffel
DUFFEL_ENV=test
DUFFEL_ACCESS_TOKEN=<your-test-token>
DUFFEL_API_VERSION=v2
DUFFEL_TIMEOUT_SECONDS=20
DUFFEL_MAX_RETRIES=1
DUFFEL_MAX_FLIGHT_OFFERS=5
DUFFEL_MAX_STAY_RESULTS=10
DUFFEL_ALLOW_DEMO_FALLBACK=false
```

The only accepted base URL is `https://api.duffel.com`. Every request sends bearer authorization,
`Duffel-Version: v2`, JSON accept/content headers, and a bounded timeout. The access token lives only
in `SecretStr` settings and the process-owned client; it is never passed through MCP arguments,
LangGraph State, checkpoints, SSE, metrics, logs, documentation, or frontend code.

FastAPI direct mode owns one shared `httpx.AsyncClient` for its lifespan. The HTTP MCP server is an
independent process, reads its own environment, owns a separate client, and closes it on shutdown.
The STDIO weather/route server needs no Duffel credential.

## Data mode and transport mode are independent

All four combinations are valid:

| Data mode | Transport | Result |
| --- | --- | --- |
| demo | direct | five in-process demo searches |
| demo | mcp | five demo tools over MCP |
| duffel | direct | Duffel Flights/Stays in process; three demo searches |
| duffel | mcp | HTTP MCP owns Duffel Flights/Stays; three demo tools |

`TRAVEL_DATA_MODE` selects facts. `TRAVEL_SEARCH_BACKEND_MODE` selects the invocation path. MCP is
not synonymous with live data, and direct is not synonymous with demo data.

## Flights mapping

P17 searches outbound **one-way** travel only. The selected flight and total plan estimate exclude
return airfare. Domain/OpenAPI descriptions, plan Markdown, README and the frontend disclose this;
no round-trip or booking support is implied.

The existing domain represents one-way planning, so the Offer Request contains one slice, one adult
passenger entry per traveler, and economy cabin. Origin and destination are resolved through Duffel
Places; an LLM never guesses IATA codes or coordinates.

Each returned offer maps:

- `total_amount` with `Decimal` and its actual currency;
- provider offer ID and optional expiry as non-booking metadata;
- every slice segment, not only the first;
- full operating-carrier name, operating flight number, IATA endpoints, times, and duration;
- stop count as `segment_count - 1`;
- whole-slice duration and first-departure/final-arrival timestamps.

The frontend lists connecting segments and the full operating carrier. Volatile offer ID, expiry,
and source metadata do not change the grounded candidate ID.

The external response projection follows Duffel's current v2 schemas rather than the smaller local
fixtures. Third-party objects ignore additional fields that this project does not consume, while
every consumed field remains typed. Marketing and operating carriers, plus segment origin and
destination, are nested provider objects; both carrier flight numbers remain strings. Duffel marks
slice and segment duration nullable and describes each non-null value as ISO 8601, so Pydantic's
duration parser is used instead of a narrower local regular expression. When either duration is
null, the mapper calculates elapsed minutes from the airports' IANA time zones and local schedule
instead of inventing a duration. Some real offers omit the operating flight number; in that case
the strictly typed marketing carrier code and flight number provide the identifier, while the UI
still displays the legally important full operating-carrier name. Places also marks its nested
`airports` list nullable, so an airport suggestion does not need to carry an empty list.

Flight Offer Requests explicitly send `return_offers=true&view=offers`. This matches Duffel's
documented default flat response shape: a top-level `data` Offer Request containing `offers`.

## Stays mapping

Stays search uses destination latitude/longitude, a five-kilometre radius, inclusive project start
date, exclusive provider checkout date, adult guest entries, and one room. Since `TripRequirements`
has no room count, P17 supports only one room for one or two adults. Other party sizes return
`duffel_unsupported_request` before a remote Stays call.

Duffel documents `cheapest_rate_total_amount` as the total for the room, all nights, and all guests,
including amounts due at booking. The existing domain needs `price_per_night`, so P17 calculates:

```text
nights = (project end_date + 1 day) - start_date
price_per_night = total stay Decimal / nights
```

Property star rating and guest review score are separate nullable values. Missing rating stays null;
it never becomes zero or a fabricated 4.5. Nullable amenities become an empty list. If both hotel
and resolved-center coordinates exist, distance is a clearly derived Haversine value; otherwise it
is null. Accommodation ID is stable provider metadata; search-result ID is volatile and excluded
from candidate identity.

## Errors, retry, and fallback

External failures cross the application as stable `duffel_*` codes. Raw provider messages, bodies,
headers, URLs with queries, tracebacks, DSNs, and tokens are not public.

The client retries timeout/transport errors, 429, 503, and 504 within the configured retry ceiling.
It does not retry 400, 401, 403, 500, 502, malformed JSON, or schema errors. Duffel's
`ratelimit-reset` hint is capped at two seconds so a request cannot sleep for an unbounded period.
Cancellation propagates and is not converted into a provider error.

`DUFFEL_ALLOW_DEMO_FALLBACK=false` prevents silent substitution. If an operator explicitly enables
fallback, the resulting facts use `demo_fallback` in domain models, search summary, final plan, SSE,
metrics, MCP, logs, and UI. Flights and hotels are critical searches, so a strict Duffel failure
ends planning safely rather than returning an old or invented plan.

## API, persistence, SSE, and grounding

`GET /api/v1/travel-data/status` reports only mode, provider, configured boolean, environment,
external/demo kind lists, fallback setting, and a no-probe Stays access state. It never calls Duffel.
In Duffel mode a missing token makes `/ready` return 503 while `/health` remains 200. Streaming
preflight also returns HTTP 503 before committing SSE headers.

Mapped domain models and bounded source values may enter strict MessagePack checkpoints. Access
tokens, authorization, raw responses, `httpx` clients, configs, and exceptions may not. Search SSE
completion can expose only kind, status, result count, and source. The graph still runs once per
request and still fans out five searches with LangGraph `Send`; Duffel Flights and Stays can run in
parallel. Qwen receives bounded candidates only, and Reviewer loop limits remain application-owned.

## Metrics and Grafana

P17 adds:

- `travel_planner_external_requests_total{provider,operation,status}`;
- `travel_planner_external_request_duration_seconds{provider,operation,status}`;
- `travel_planner_search_source_total{kind,source,status}`.

Operations and source values are fixed allowlists. Offer/hotel IDs, route, airport, city, price,
user, thread, request ID, error text, and token are never labels. The provisioned dashboard has 32
panels after adding External API Requests, External API Errors, External API p95, and Search Data
Sources.

## Verification

Ordinary offline validation never contacts Duffel:

```bash
uv run pytest -q
```

Real test-mode transport is separately gated:

```bash
RUN_DUFFEL_INTEGRATION_TESTS=1 \
uv run pytest -m duffel_integration -q

uv run python scripts/check_duffel.py
uv run python scripts/check_duffel.py --check-stays
uv run python scripts/check_duffel.py --require-stays
```

The default smoke command performs only the Flights request, using Duffel's documented predictable
LHR→DXB route. Stays is attempted only with `--check-stays` or `--require-stays`; the latter makes
missing account access a failure. Schema failures report only provider, operation, validation error
count, Pydantic location, and error type—never input values or response bodies. No real result may
be reported unless the corresponding command was actually run.

## Current limitations

- In external mode Flights use Duffel and Hotels use LiteAPI; three categories stay demo.
- Initial Stays support is one room and one or two adults.
- No FX conversion is invented; a result currency must be supported and match the trip currency.
- Place ambiguity returns a safe failure rather than asking an LLM to guess.
- User-provided Duffel Flights Developer Test smoke succeeded repeatedly (latest 70 offers;
  earlier 71, 75, 81). This is verified user evidence, not a fresh call by this continuation.
- Duffel Stays adapter is optional; real acceptance is NOT VERIFIED. Access was requested but
  not granted through 2026-09-08; approval no longer blocks P17. Production behavior is unverified.
- There is no booking, payment, authentication, public deployment, or production-readiness claim.
