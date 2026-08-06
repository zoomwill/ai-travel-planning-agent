# Prompt P00 — Environment and Repository Audit

Read `AGENTS.md` and all overview documents. Audit only; do not build features.

1. Explain the repository in beginner language.
2. Check Git status and versions of Python, uv, Docker and Docker Compose.
3. Run `uv sync`.
4. Run all checks from AGENTS.md.
5. Start FastAPI temporarily and verify `/health`.
6. Stop it cleanly.
7. Fix only starter problems needed for these checks.
8. Rerun everything.
9. Show changed files, commands, outputs, manual verification and a commit message.
10. Stop. Do not install LangGraph, Chroma client, Redis client, PostgreSQL driver or FastMCP.
