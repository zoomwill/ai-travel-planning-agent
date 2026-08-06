# Prompt P08 — Planner/Reviewer Reflection Loop

Complete only Phase 08.

Add an LLM client abstraction with deterministic fake tests. Planner reads requirements and search results. Reviewer returns structured completeness, feasibility, personalization, budget fit, total and critique. Configure threshold/max iterations. Loop with critique, prevent infinite loops, and test pass/revise/forced-output/malformed-review paths. Do not connect real Qwen. Run all checks and stop.
