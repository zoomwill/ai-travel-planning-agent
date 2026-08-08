# Phase P03 Domain Models and Deterministic Mock Providers

Phase P03 gives the project a shared travel vocabulary. Before this phase, FastAPI could prove
that PostgreSQL, Redis, and Chroma were reachable, but the Python code had no agreed shape for a
trip request, flight, hotel, weather result, route, plan, or review.

This phase does not plan a trip yet. It only defines valid data and provides predictable local
examples that later phases can call.

## P02 and P03 are different layers

- P02 is application infrastructure: settings, database clients, lifespan ownership, liveness,
  and readiness.
- P03 is travel domain code: what travel data means and how local mock travel services behave.

The P03 code does not contact PostgreSQL, Redis, Chroma, an LLM, or a third-party travel API.

## What Pydantic does

Pydantic turns Python type annotations into runtime validation. For example, `start_date: Date`
means the stored value is a real Python date, while `budget: Decimal = Field(gt=0)` means a zero or
negative budget is rejected with a structured `ValidationError`.

All P03 domain classes inherit from Pydantic `BaseModel`. They:

- describe every field;
- reject unknown fields, which catches misspellings;
- strip surrounding whitespace from strings;
- include example data in generated JSON Schema;
- use current Pydantic v2 validators rather than the removed v1 `root_validator` style.

Money uses `Decimal` instead of `float` because decimal amounts such as `0.10` should not acquire
binary floating-point rounding artifacts. Currency uses an explicit enum: `CNY`, `USD`, `JPY`, or
`EUR`.

## Domain models

| Model | Purpose | Important validation |
|---|---|---|
| `TripRequirements` | A complete user trip request | Ordered dates, positive budget and travelers |
| `FlightOption` | One flight search result | Positive price/duration, arrival after departure |
| `HotelOption` | One hotel search result | Rating from 0 to 5, positive nightly price |
| `Attraction` | One place to visit | Nonnegative admission estimate and explicit currency |
| `WeatherSummary` | Weather for one city and date | Rain probability from 0 to 100 |
| `RouteSummary` | Point-to-point transport estimate | Positive duration, nonnegative cost |
| `DailyItinerary` | Activities for one trip day | Day number starts at 1 and activities are nonempty |
| `TravelPlan` | Future final-plan data shape | At least one day, consistent currency and trip dates |
| `QualityScore` | Future reviewer result | Every score stays between 0 and 100 |
| `ToolError` | Safe future tool failure | No traceback field or arbitrary connection details |

`Currency` and `TransportMode` are enums. An enum is a small list of allowed values, which prevents
different parts of the project from inventing spellings such as `usd`, `US Dollars`, and `USD` for
the same concept.

## Model and service responsibilities

A model answers: “Is this data valid, and what fields does it contain?” It should not search the
internet or decide which hotel is best.

A service answers: “Given valid input, what business result should be returned?” P03 services
return Pydantic models, so invalid mock data fails immediately during development.

The separation is:

```text
TripRequirements model
        ↓
mock provider service
        ↓
FlightOption / HotelOption / Attraction / WeatherSummary models
```

## Deterministic mock providers

The package `app/services/mock_providers` exposes:

- `search_flights(requirements)`;
- `search_hotels(requirements)`;
- `search_attractions(requirements)`;
- `get_weather(requirements)`;
- `get_route(origin, destination)`.

“Deterministic” means the same input produces equal model values every time. The providers use
fixed city templates and process-independent calculations derived only from input text and trip
dates. They do not use `random`, the current clock, Python's process-randomized `hash()`, network
requests, or environment secrets.

Tokyo and Shanghai have curated mock examples. Other nonblank destinations use a stable generic
fallback so tests can compare different cities without pretending to have live inventory.

## Why no real travel API yet

Real provider APIs introduce credentials, network failures, rate limits, changing inventory,
licensing rules, and cost. Those variables make beginner tests harder to understand. Deterministic
mocks let future Agent and planning phases be tested locally before a real provider adapter is
chosen intentionally.

Mock prices are invented examples. The fixed currency factors are not current exchange rates.
Mock weather is not a forecast, and mock flights/hotels are not available inventory.

## How future Agents will use these models

Later phases can accept a `TripRequirements` object, call services, and exchange validated result
models instead of loosely structured dictionaries. A future planner can select a `FlightOption`
and `HotelOption`, build `DailyItinerary` objects, and return a `TravelPlan`. A future reviewer can
return `QualityScore`, while failed tools can add safe `ToolError` values.

P03 does not implement those Agents or decisions; it only creates their shared contracts.

## Run the tests

Run only the P03 tests:

```bash
uv run pytest -q tests/domain tests/services
```

Run the complete project checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

No Docker service is needed for the P03 unit tests. The existing Docker integration test remains
explicitly opt-in exactly as it was in P02.
