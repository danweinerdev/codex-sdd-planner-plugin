# Orchestration Model

The primary Codex agent owns user communication, approvals, scope decisions, and final synthesis. It may delegate independent reading, implementation, or review work to Codex collaboration agents when they are available.

## Principles

1. Delegate only independent, bounded work. Keep cross-cutting decisions and artifact status changes with the primary agent.
2. Parallelize tasks only when their expected file ownership and dependencies do not overlap.
3. Treat agent output as evidence to validate, not as proof. Preserve actual command output for verification claims.
4. Skills must work without collaboration agents. Fall back to a transparent single-agent workflow and never claim independent review when none occurred.
5. After compaction, re-read plan and phase frontmatter plus unresolved user questions; do not rely on remembered status.

## Session orientation

Read `planning-config.json`, active plan frontmatter, current phase task status, and the latest debrief before resuming implementation. Read full artifact bodies only when the current decision needs them.
