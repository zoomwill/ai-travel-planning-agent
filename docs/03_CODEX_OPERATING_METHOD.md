# How to Work with Codex on This Project

## Why one giant prompt is the wrong approach

A giant prompt encourages the coding agent to make too many assumptions, install incompatible libraries, hide failures and leave the beginner unable to understand the result.

The correct unit of work is one phase.

## The repeated loop

For every phase:

1. Open the matching prompt.
2. Paste it into Codex.
3. Let Codex inspect the repository.
4. Review Codex's proposed plan.
5. Allow file edits and safe terminal commands.
6. Read the test output.
7. Open the changed files.
8. Run the commands yourself once.
9. Create a Git commit.
10. Continue to the next phase.

## Failure follow-up prompt

```text
Do not add new features. Diagnose the current failure only.
Explain the root cause in beginner language.
Show the exact failing command and the smallest fix.
After the fix, rerun the same command plus the full test suite.
Do not claim success until the command output is clean.
```

## Explanation prompt

```text
Explain this file as if I know basic variables and functions but not frameworks.
Go top to bottom. For each class and function explain why it exists, what enters,
what leaves, who calls it, and one concrete example. Do not edit code.
```
