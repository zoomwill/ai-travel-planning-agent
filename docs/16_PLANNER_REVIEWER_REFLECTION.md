# P09 — Planner–Reviewer Reflection Loop

P08 answered “how can five independent searches run and merge safely?” P09 answers “how can a
draft be checked, revised, and stopped safely?” Everything remains deterministic and local. No
LLM, real travel API, prompt service, or human reviewer is involved.

```text
START
  -> Memory Context
  -> Router
  -> Retriever
  -> Prepare Search Tasks
  -> Send(Search Worker x 5)
  -> Aggregate Search Results
  -> Initialize Review Cycle
  -> Planner
  -> Reviewer
       |-- revise ----------> Planner
       `-- accept/forced ---> Finalize Plan
  -> END
```

## 22 beginner concepts

1. **P08 versus P09:** P08 gathers flight, hotel, attraction, weather, and route data. P09 never
   repeats those searches; it reviews plans built from the same saved results.
2. A **reflection loop** is a bounded graph cycle: Planner drafts, Reviewer checks, and Planner may
   revise. It is not Python recursion and does not call the graph from inside a node.
3. **Planner** owns plan construction. **Reviewer** owns scoring and feedback. Reviewer never edits
   the draft directly.
4. A **structured review** is validated data: round, fingerprint, four scores, decision, issue
   codes, critique, and suggested changes. It is safer to route than free-form text alone.
5. **Completeness** checks required flight/hotel content, all requested dates, non-empty itinerary,
   positive total cost, and honest notices for unavailable non-critical data.
6. **Feasibility** checks dates/day numbers, route consistency, non-negative costs, and whether a
   day contains more than two optional attraction visits.
7. **Personalization** checks current and remembered preference tokens against actual activities,
   retrieved context, and plan explanation. A user with no preferences receives 100 rather than an
   unfair zero.
8. **Budget fit** is 100 inside budget. Above budget it is
   `round(100 * budget / total_cost, 2)`. The Reviewer never changes the budget or invents prices.
9. **Overall score** is the equal-weight mean of the four dimensions, rounded to two decimals.
   These weights are transparent defaults, not a measured or researched quality result.
10. The **threshold** defaults to 80. An overall score of 80.00 passes; 79.99 does not.
11. A **critique** is concrete human-readable guidance paired with stable machine issue codes.
12. **RevisionPolicy** translates actionable issues into four controls: lower-cost options, daily
    attraction limit, preference priority, and unavailable-data notices.
13. Planner really applies feedback. Budget policy selects cheaper existing provider results;
    pace policy changes activity lists; preference policy reorders existing attractions.
14. Changing only Markdown would not be a real revision. Tests compare flight/hotel/activity
    fields and draft fingerprints before accepting a claimed change.
15. LangGraph's current `add_conditional_edges` routes Reviewer back to Planner only for `revise`.
    `accept`, `forced_finalize`, and safe reviewer failure route to Finalize.
16. Every loop needs a **business termination condition**. Reviewer can run at most
    `REVIEW_MAX_ROUNDS` times; the default is exactly three reviews, not four.
17. `GRAPH_RECURSION_LIMIT=50` is a second safety layer. It is passed as the top-level
    `config["recursion_limit"]`, outside `configurable.thread_id`. LangGraph then raises
    `GraphRecursionError` instead of looping forever.
18. `draft_plan` is the JSON-safe plan under review. `travel_plan` remains empty until Finalize
    validates the last draft and records an honest outcome.
19. `review_history` stores JSON-safe round summaries in checkpoints. Its pure reducer deduplicates
    by `(review_round, draft_fingerprint)` and sorts by round rather than current time.
20. FastAPI's lifespan still owns one compiled PostgreSQL graph. Restarting Uvicorn opens new
    saver/store connections and can read the saved final state and history.
21. **Forced finalize** means the score stayed below threshold when the maximum review round ended.
    The final Markdown says so explicitly; it never pretends the plan passed.
22. P09 is complete only when ordinary tests need no Docker, scripted revision changes a real
    draft, max rounds stop exactly, strict PostgreSQL state reopens, real HTTP accepts and forces
    the correct cases, new-thread memory remains isolated, and no P10 feature is added.

## Exact deterministic scoring rules

Every dimension starts at 100 and never falls below zero.

Completeness deductions:

- missing flight: 25;
- missing hotel: 25;
- empty itinerary: 30;
- dates do not exactly cover the inclusive request: 20;
- missing/non-positive total: 20;
- one or more unavailable search kinds: 10;
- unavailable kinds not explicitly disclosed: another 10.

Feasibility deductions:

- itinerary dates or day numbers differ from the request: 30;
- any day has more than two `Visit ...` attraction activities: 25;
- missing/non-positive total or negative daily cost: 25;
- flight route differs from requirements: 20;
- hotel city differs from destination: 15.

Personalization uses normalized English alphanumeric tokens and only a small singular/plural
normalization. All meaningful tokens in a preference must appear in plan evidence. Its formula is
`100 * reflected_preferences / total_preferences`. No-preference input receives 100.

Budget fit is 100 when `total_cost <= budget`; otherwise it uses the stable ratio above.

## Review data

`PlanReview` contains:

- `review_round`;
- SHA-256 `draft_fingerprint`;
- the existing P03 `QualityScore`;
- `accept`, `revise`, or `forced_finalize`;
- stable `ReviewIssueCode` values;
- non-empty critique;
- structured suggested-change strings.

The fingerprint hashes canonical JSON from every `TravelPlan` field, including Markdown, using
sorted keys and fixed separators. It never uses Python `hash()`, random data, or the current time.

State also stores:

- `current_review` as JSON;
- `review_history` as JSON;
- completed `review_round` count;
- next-round `critique` and JSON `revision_policy`;
- `pending`, `accepted`, `forced_finalized`, or `failed` status;
- a safe `finalization_reason`;
- the actual feedback applied by the latest Planner run.

## Resetting a reused thread

`initialize_review_cycle` runs after P08 aggregation and before Planner. For an existing persistent
thread it uses LangGraph `Overwrite` to clear draft, review, history, policy, status reason, and old
final plan. It does not touch current search results, RAG context, or user memory.

`TravelPlanState` is `total=False`, so a minimal first-run test input may omit these channels. In
LangGraph 1.2.10, an absent reducer channel cannot unwrap an `Overwrite` as its very first value.
The node therefore writes a raw safe default only for a truly absent first-run channel and uses
`Overwrite` whenever the field already exists. Real API initial states explicitly include every
field, and a reused thread always takes the Overwrite path.

## Failure behavior

- Critical flight/hotel failure skips Reviewer and keeps P08's safe HTTP 503.
- Non-critical search failure creates an honest degraded draft that can still be reviewed.
- Reviewer exception runs once, stores only `reviewer_failed`, and does not leak exception text.
- Invalid reviewer structure or mismatched fingerprint becomes `review_output_invalid`.
- Invalid revision policy becomes `revision_failed`.
- Invalid/missing final draft becomes `finalization_failed`.
- Official recursion exhaustion maps to `graph_recursion_limit_reached` without runnable config or
  checkpoint internals.

## API compatibility

- `POST /api/v1/plans/mock` remains the P04 single-pass deterministic endpoint.
- `POST /api/v1/agents/plans` uses the review loop but still returns a direct `TravelPlan`.
- The persistent plan response adds review status, rounds, final score, finalization reason, and a
  safe validated review summary.
- The state endpoint adds only status, round, score, reason, draft presence, and history count. It
  does not expose Reviewer objects, Send payloads, exceptions, prompts, DSNs, or serializer data.
- History remains bounded by the caller's limit. Its exact checkpoint count is deliberately not
  fixed because each Planner/Reviewer round adds valid super-steps.

## Run locally

Start Docker Desktop, then run:

```bash
docker compose up -d --wait --wait-timeout 120
uv run python scripts/check_infra.py
uv run python scripts/setup_langgraph_persistence.py
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Persistent request, state, history, and preference commands remain the same as P07/P08. Persistent
responses now contain the safe review fields described above.

Run ordinary checks without Docker integration:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

Explicitly run PostgreSQL integration after Docker is ready:

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

## Current limits and future replacement

- The Reviewer is a hand-written deterministic ruleset, not a model or a human judgment.
- Simple token matching is not multilingual semantic preference evaluation.
- The score has not been calibrated against users, experts, benchmarks, or production traffic.
- P09 measures no quality, latency, throughput, or conversion improvement.
- Revision can only choose or rearrange existing deterministic provider results.
- A later phase could implement a real LLM behind the same `PlanReviewer` Protocol, but it would
  need schema validation, timeout, retry policy, deterministic tests, privacy review, and explicit
  user approval. P09 does not install or call one.
- There is still no MCP, SSE, advanced RAG, authentication, frontend, or real booking.

Current LangGraph references used for the implementation:

- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [`add_conditional_edges` reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)
- [`GraphRecursionError` reference](https://reference.langchain.com/python/langgraph/errors/GraphRecursionError)
