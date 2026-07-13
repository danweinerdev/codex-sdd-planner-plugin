---
name: implement
description: "Execute an approved spec-driven implementation plan phase, update task statuses, and verify code changes. Use when asked to implement an active plan or execute a specific phase or task."
---

# Execute a Plan Phase

## Resources

Read `shared/codex-runtime.md`, `shared/path-resolution.md`, `shared/vcs-detection.md`, `shared/autonomy.md`, and the relevant language-verification skill.

## Preconditions

Read the active plan and phase frontmatter. Confirm the target repository, task dependencies, acceptance criteria, and verification commands. If the plan contradicts the codebase, has an unresolved external dependency, or lacks required clarification, stop and surface the mismatch rather than silently changing scope.

## Process

1. Select unfinished tasks whose dependencies are complete. Group independent tasks only when their expected file ownership does not overlap.
2. For each task, inspect the relevant specification/design, code conventions, and test infrastructure. Implement the task and its tests as a focused change.
3. Run the required verification and relevant project checks. Fix failures caused by the change. Report pre-existing failures distinctly, with actual output.
4. Optionally use Codex collaboration agents for independent tasks when available. Give each agent one task, target path, acceptance criteria, and verification requirements. Do not depend on named plugin agents, Claude models, or a `Task` API.
5. Before marking a task complete, review its diff for correctness, scope, tests, and maintainability. Use the Code Review skill for phase-level review or material risk.
6. Update phase task status, subtask checkboxes, and `updated` frontmatter only after evidence-backed completion. Commit only when the user or repository policy calls for it.

## Escalate

Ask the user before destructive or production-impacting operations, when requirements are ambiguous, when implementation reveals unplanned scope, or after two failed attempts to resolve a blocking verification failure.

## Output

For each completed task report files changed, verification commands with actual results, status updates, and any deferred findings. Keep the plan artifact as the source of truth.
