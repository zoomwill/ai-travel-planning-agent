# Working Rules

Follow these rules for every task.

## 1. Read before changing

Before editing code:

1. Read this file.
2. Read `docs/01_SOURCE_SPECIFICATION.md`.
3. Read `docs/02_PHASE_PLAN.md`.
4. Read the current phase prompt.
5. Inspect the existing repository and tests.

## 2. Never silently skip steps

For every task:

1. State the goal in plain language.
2. List the files you expect to change.
3. Make the smallest coherent change.
4. Run formatting, linting, type checks, and tests.
5. Explain failures in beginner language.
6. Fix failures before claiming success.
7. Summarize exactly what changed.

## 3. Do not fabricate implementation status

Do not claim a feature works unless executed an appropriate test or command.

Do not invent:

- benchmark improvements,
- latency numbers,
- QPS,
- recall or precision improvements,
- production readiness,
- external API success,
- database persistence success.

Record unverified goals as goals, not results.

## 4. Source fidelity and current APIs

The source screenshots contain architecture descriptions and pseudocode. They may use outdated or approximate APIs.

When source pseudocode conflicts with current official documentation:

1. Use the current supported API.
2. Preserve the intended behavior.
3. Add a note to `docs/implementation-notes.md` containing:
   - source intent,
   - actual implementation,
   - reason for the difference.

## 5. Beginner safety

- Prefer readable code over clever abstractions.
- Add docstrings to public classes and functions.
- Use type hints.
- Avoid metaprogramming unless required.
- Avoid global mutable state.
- Never delete large sections without explaining why.
- Never expose secrets.
- Never place real API keys in source files.
- Use `.env` and `.env.example`.

## 6. Testing policy

Each phase must include or update tests.

Minimum commands:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

When a tool is unavailable, explain how to install it instead of pretending it ran.

## 7. Git policy

At the end of a successful phase:

1. Show `git diff --stat`.
2. Suggest a commit message.
3. Do not rewrite Git history.
4. Do not force-push.
5. Do not commit secrets or generated database files.

## 8. Architecture boundaries

Keep these responsibilities separate:

- `api`: HTTP and SSE boundaries.
- `graphs`: LangGraph state, nodes, edges, routing.
- `agents`: prompts and LLM-facing agent logic.
- `rag`: ingestion, chunking, retrieval, reranking.
- `mcp`: MCP servers, clients, adapters.
- `memory`: checkpoints, store, preference memory.
- `services`: business services and external providers.
- `observability`: logging, metrics, tracing.
- `core`: settings, shared exceptions, dependency wiring.

## 9. External services

Start with mock providers. Real flight, hotel, map, weather, or LLM APIs are added only after the local workflow is stable.

Every external call must have:

- timeout,
- structured error,
- retry policy where appropriate,
- deterministic mock for tests.
