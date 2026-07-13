---
name: simplify
description: "Simplify implemented code while preserving behavior. Use after implementation when asked to reduce complexity, remove duplication, or improve maintainability with verification."
---

# Code Simplification

## Resources

Read `shared/codex-runtime.md`, `shared/path-resolution.md`, and `shared/vcs-detection.md`.

## Process

1. Identify target files or a completed plan phase. Read the code, tests, callers, and relevant recent diff.
2. Produce a short list of validated simplifications. For each, state the behavior preserved, files affected, risk, and verification command.
3. Present behavior-affecting changes for user approval. Safe, local refactors may proceed autonomously when the request authorizes implementation.
4. Apply focused changes and run the project's relevant tests, type checks, linters, or build commands. If verification fails, fix the change or restore the affected change before reporting failure.
5. If linked to a plan, record completed simplification work in its debrief or phase only after verification.

## Constraints

- Do not rewrite working code wholesale.
- Do not call a change verified without command output.
- Prefer existing project conventions over abstract cleanup preferences.
- Do not rely on Claude agent names or plugin-defined worker roles.
