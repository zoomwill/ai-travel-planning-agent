# Phase P04 — Deterministic Planning MVP

Phase P04 turns the validated P03 mock data into one complete travel plan. Although the phase is
called “Single-Agent Planning MVP” in the architecture plan, there is no AI Agent or LLM in this
phase. An ordinary Python function applies fixed rules, so the same input always produces the same
output.

## What happens to a request

`POST /api/v1/plans/mock` accepts a JSON request shaped like `TripRequirements`. FastAPI asks
Pydantic to validate it first. Invalid or missing fields receive HTTP 422 automatically.

For a valid request, the layers are:

1. `app/api/routes/plans.py` receives HTTP data and calls the planning service.
2. `app/services/planning_service.py` calls all five P03 mock providers.
3. The service selects the first flight and the highest-rated hotel.
4. It creates one `DailyItinerary` for every date from `start_date` through `end_date`, inclusive.
5. It returns one validated `TravelPlan`. FastAPI serializes that model to JSON.

The API route does not create or call providers itself. `PlanningProviders` groups five callable
dependencies in one immutable object. Tests can replace one callable, and later phases can supply
real adapters without moving planning rules into the HTTP layer.

## Fixed itinerary rules

- Day 1 includes arrival, hotel check-in, the first route, and one attraction.
- Each later day includes two attractions.
- If a trip has more activity slots than the three mock attractions, the service cycles through
  them in the same order.
- Every day includes its matching mock weather summary.
- City names come from the request; the planning service does not hard-code Tokyo.

The selected flight and hotel prices already use the request currency. Daily activity cost is the
sum of that day's attraction admission estimates multiplied by the number of travelers. The total
uses the P04 formula exactly:

```text
selected flight price
+ selected hotel price per night × inclusive trip days
+ sum of daily activity costs
```

The mock route is descriptive itinerary information. Its estimate is not added to the formula.
When the estimated total exceeds the requested budget, the API still returns HTTP 200 with a
`budget_warning`; it does not hide an otherwise useful plan.

## Start and call the API

Start Docker Desktop and the P01 services first because the application lifespan owns the P02
infrastructure clients:

```bash
docker compose up -d --wait --wait-timeout 120
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, send a request:

```bash
curl --noproxy '*' --max-time 10 --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "origin": "Shanghai",
    "destination": "Tokyo",
    "start_date": "2026-09-01",
    "end_date": "2026-09-05",
    "budget": "10000.00",
    "currency": "CNY",
    "travelers": 1,
    "preferences": ["photography", "vintage shopping"]
  }' \
  http://127.0.0.1:8000/api/v1/plans/mock
```

The response is one JSON `TravelPlan`. Its `daily_itinerary` is structured for programs, while
its `markdown` field presents the same plan for a person to read.

`--noproxy '*'` makes this command contact the local server directly even when the computer has a
system proxy. `--max-time 10` prevents a network mistake from waiting forever.

Stop Uvicorn with `Control-C`. To stop infrastructure while retaining named-volume data, run:

```bash
docker compose stop
```

## Error behavior

- Invalid request data returns HTTP 422 with FastAPI's validation details.
- A provider or planning-stage failure returns HTTP 503 with only a safe stage name.
- Raw exceptions, tracebacks, passwords, and internal connection strings are not returned.

## Run the tests

Ordinary tests use local resource doubles and deterministic providers, so they do not require
Docker or network access:

```bash
uv run pytest -q tests/services/test_planning_service.py tests/api/test_plans.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

## Intentional limitations

- All flight, hotel, attraction, weather, and route data is invented deterministic test data.
- No availability is checked and no booking is made.
- The cost formula is an estimate, not a real quote, tax calculation, or exchange rate.
- Preferences are preserved in `TripRequirements` but do not rank activities yet.
- There is no LangGraph, Agent, LLM, prompt, RAG, MCP, SSE, persistence, cache, or authentication.
