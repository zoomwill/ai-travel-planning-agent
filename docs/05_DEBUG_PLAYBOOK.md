# Beginner Debugging Playbook

1. Copy the exact command and error; do not summarize from memory.
2. Decide whether the problem is installation, import, connection, validation, graph, tool or retrieval.
3. Reduce to the smallest failing test.
4. Do not fix validation errors by deleting validation.
5. Record important failures and fixes in `docs/implementation-notes.md`.

Use this Codex prompt:

```text
Do not add new features. Reproduce the error first. Explain the root cause in beginner
language. Make the smallest fix. Rerun the focused test and then the full checks from
AGENTS.md. Show the command output and stop.
```
