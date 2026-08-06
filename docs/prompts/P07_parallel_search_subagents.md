# Prompt P07 — Parallel Search Subagents

Complete only Phase 07 using current LangGraph parallel dispatch and reducers.

Run flight, hotel, attraction, weather and route branches concurrently with mocks. Each writes its own field; reducers merge safely; errors append to tool_errors; one failure preserves other results. Test success, failure, completion order and deterministic merged state. Document super-steps and reducers. Run all checks and stop.
