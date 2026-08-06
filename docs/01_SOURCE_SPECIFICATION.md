# Source-derived Project Specification

This specification preserves the terminology and architecture shown in the supplied screenshots. It distinguishes source-supported design from details that must be chosen during implementation.

## 1. Product goal

Build an intelligent travel planning system that can:

- collect incomplete travel requirements through multi-turn conversation,
- retrieve travel knowledge and live tool data,
- generate a detailed itinerary,
- automatically review itinerary quality,
- revise the itinerary through a bounded reflection loop,
- stream the result to the user,
- retain short-term conversation state and long-term preferences,
- expose end-to-end observability.

## 2. Main Agent roles

### Router Agent

- Reads the latest user message and current state.
- Classifies intent.
- Routes to the appropriate downstream workflow.
- Example intents:
  - incomplete travel request,
  - travel information lookup,
  - full plan generation,
  - modification of an existing plan,
  - unrelated direct reply.

### Requirement Collection Agent

- Collects missing fields through follow-up questions.
- Writes structured requirements.
- Does not generate the final itinerary.

Minimum requirement fields:

- origin,
- destination,
- start date,
- end date or number of days,
- budget,
- travel preferences,
- party size,
- optional constraints.

### Information Retrieval Agent

- Retrieves unstructured travel documents through RAG.
- Calls tool subagents for flights, hotels, attractions, maps, and weather.
- Can dispatch independent tasks in parallel.

### Planner Agent

- Reads requirements, retrieved documents, and tool results.
- Produces a structured itinerary draft.
- On later rounds, reads reviewer critique and revises the draft.

### Review Agent

- Scores the plan with structured output.
- Source screenshots use four dimensions:
  - completeness,
  - feasibility,
  - personalization,
  - budget fit.
- If below threshold, writes a concrete critique.
- If above threshold or maximum iterations reached, routes to final output.

## 3. Shared graph state

The source uses a shared typed state as the communication bus. The implementation should include fields equivalent to:

```python
class TravelPlanState(TypedDict):
    messages: list
    query_type: str | None
    user_requirements: RequirementModel | None
    retrieved_docs: list
    flight_results: list
    hotel_results: list
    attraction_results: list
    weather_results: list
    map_results: list
    draft_plan: str | None
    critique: str | None
    quality_score: float | None
    iteration_count: int
    final_plan: str | None
    tool_errors: list
```

Parallel result fields must use reducers that append or merge rather than overwrite.

## 4. Collaboration modes

The source combines three patterns:

### Router routing

Used at the entry point for intent classification.

### Handoff

An Agent signals that control should move to another Agent after completing its responsibility.

### Parallel Subagents

A supervisor dispatches independent searches simultaneously. Results are merged through reducer semantics.

## 5. Reflection loop

Expected loop:

1. Planner writes `draft_plan`.
2. Reviewer writes `quality_score` and possibly `critique`.
3. If score is below threshold and iteration limit not reached:
   - increment `iteration_count`,
   - route back to Planner,
   - Planner incorporates critique.
4. Otherwise write `final_plan`.

The source frequently uses a threshold equivalent to `0.8` or `80/100` and a maximum of three review rounds. These values should be configuration, not hard-coded throughout the codebase.

## 6. RAG pipeline

The source describes a four-stage retrieval pipeline:

1. Multi-Query expansion:
   - generate several semantic variants of the query.
2. Hybrid retrieval:
   - dense vector retrieval in ChromaDB,
   - BM25 sparse retrieval,
   - merge ranked lists with Reciprocal Rank Fusion.
3. Reranking:
   - rerank a limited candidate set using an LLM or reranker model.
4. Parent-document mapping:
   - retrieve smaller child chunks,
   - return the corresponding larger parent document for context completeness.

Additional source ideas:

- Redis caches repeated retrieval results.
- metadata filters include city, region, document type, source, and update date.
- HNSW parameters should be configurable and evaluated, not copied blindly.
- source examples mention `M`, construction effort, and search effort.

## 7. MCP tool layer

The source uses:

- FastMCP for exposing Python functions as MCP tools,
- a multi-server MCP client for combining local and remote servers,
- local `stdio` transport,
- remote Streamable HTTP transport,
- tool discovery and conversion into model-callable tools.

Initial tools should be mock implementations:

- `search_flights`,
- `search_hotels`,
- `search_attractions`,
- `get_weather`,
- `get_route`.

Real APIs should be optional provider adapters.

## 8. Memory model

### Short-term memory

- LangGraph thread state.
- Checkpoints after graph steps.
- Resume, inspection, human-in-the-loop, and fault recovery.
- Identified by a thread identifier.

### Long-term memory

- User preferences available across threads.
- Structured profile fields in PostgreSQL or LangGraph Store.
- Optional semantic memory retrieval for narrative summaries.
- Only relevant memories should be injected into prompts.

The source distinguishes long-term stable preferences from one-trip temporary preferences.

## 9. Persistence and cache

### PostgreSQL

- LangGraph checkpointer.
- LangGraph store or equivalent long-term memory store.
- travel plans.
- user profiles.

### Redis

- RAG result cache.
- tool result cache.
- rate limits.
- optional session locks.

### ChromaDB

- embeddings and document metadata.
- semantic retrieval.

## 10. API and streaming

- FastAPI HTTP API.
- health endpoint.
- planning endpoint.
- SSE stream emitting tokens and lifecycle events.
- cancellation handling.
- session or thread identifier returned to the client.

## 11. Observability

The source includes:

- LangSmith for graph, model, tool, and retrieval traces.
- structured logging through Loguru.
- Prometheus metrics.
- Grafana dashboards.

Core metrics:

- request latency,
- LLM latency,
- token use,
- graph state transition counts,
- RAG cache hit rate,
- tool call success and error rate,
- review iteration count.

## 12. Source claims that require verification

Do not present the following as achieved until measured:

- percentage improvements in recall, precision, NDCG, or context completeness,
- QPS limits,
- index build duration,
- CPU reduction,
- fixed response latency,
- production availability.

## 13. Deliberately deferred scope

The screenshots do not provide:

- the original repository,
- a complete frontend,
- real provider credentials,
- precise Qwen model endpoint configuration,
- the original dataset,
- reproducible benchmark scripts,
- exact dependency versions.

These must be implemented and documented during reconstruction.
