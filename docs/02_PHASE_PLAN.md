# Phase-by-Phase Build Plan

## Phase 00 — Environment and repository audit

Goal: prove the computer and repository are ready.

Done when Git, Python, uv, Docker and the starter tests work.

## Phase 01 — Infrastructure baseline

Start PostgreSQL, Redis and Chroma with Docker Compose and verify each service.

## Phase 02 — Configuration and application foundation

Implement typed settings, dependency clients, lifecycle management and readiness checks.

## Phase 03 — Domain models and deterministic mock providers

Define travel requirements, provider results, itinerary output and review models. Build deterministic mocks.

## Phase 04 — Single-agent planning MVP

Accept a complete request and generate a deterministic itinerary without LangGraph.

## Phase 05 — LangGraph state and persistence

Move the flow into a typed stateful graph with a development checkpointer and thread isolation.

## Phase 06 — Router and requirement collection

Support incomplete requests, simple lookups, full planning, modifications and unrelated messages.

## Phase 07 — Parallel search subagents

Run flight, hotel, attraction, weather and map tasks concurrently with safe reducers.

## Phase 08 — Planner/reviewer reflection loop

Add structured review, critique injection, configurable threshold and bounded revision.

## Phase 09 — RAG ingestion and hybrid retrieval

Implement parent-child chunks, Chroma dense search, BM25, RRF, reranking, metadata filters and Redis cache.

## Phase 10 — MCP tool services

Expose mock providers through local stdio and local HTTP FastMCP servers and discover them through one client.

## Phase 11 — PostgreSQL persistence and long-term memory

Persist checkpoints, plans and user preferences across threads while separating temporary and stable preferences.

## Phase 12 — SSE streaming and cancellation

Stream typed lifecycle and content events and cancel work on disconnect.

## Phase 13 — Observability and full-system tests

Add structured logs, Prometheus, Grafana, optional LangSmith and deterministic end-to-end tests.

## Phase 14 — Optional frontend and real providers

Only after the backend is stable, add a web UI, Qwen and selected licensed external APIs.
