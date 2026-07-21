---
name: sdd-implement
description: "Execute an approved spec-driven implementation plan phase, update task statuses, and verify code changes. Use when asked to implement an active plan or execute a specific phase or task."
---

# Execute a Plan Phase

## Resources

Before opening `shared/...`, follow symlinks in this loaded file's path, then derive `<plugin-root>` from `<plugin-root>/skills/<name>/SKILL.md`; fallback search roots are repository/user `.agents/` (including `$HOME/.agents/plugins/*/`), Codex `${CODEX_HOME:-$HOME/.codex}/plugins/cache/*/*/*/`, and runtime-configured skill roots. Accept only a root containing this skill, `shared/agent-runtime.md`, and the matching plugin manifest; never use the working directory. Then read `<plugin-root>/shared/agent-runtime.md`, `<plugin-root>/shared/path-resolution.md`, `<plugin-root>/shared/vcs-detection.md`, `<plugin-root>/shared/autonomy.md`, `<plugin-root>/shared/completion-evidence.md`, and `<plugin-root>/shared/language-verification.md` with the matching `<plugin-root>/shared/language-specs/` reference file.

**Resource boundary:** Read the plugin, all `SKILL.md` files, and `shared/` resources in place. Never copy or symlink them into the working directory, target repository, or planning root. Only generated SDD outputs may be materialized from bundled resources.

## Preconditions

Read the active plan and phase frontmatter. Read the decision ledger's frontmatter, if one exists (resolve per `shared/decision-log.md` § Ledger location), and note `accepted` entries scoped to this plan or its related specs/designs — pass the relevant statements to implementation dispatches as constraints, but never to intent-isolated review lanes. Confirm the target repository, task dependencies, acceptance criteria, and verification commands. If the plan contradicts the codebase, has an unresolved external dependency, or lacks required clarification, stop and surface the mismatch rather than silently changing scope.

## Process

1. Select unfinished tasks whose dependencies are complete. Group independent tasks only when their expected file ownership does not overlap.
2. For each task, inspect the relevant specification/design, code conventions, and test infrastructure. Implement the task and its tests as a focused change.
3. Run the required verification and relevant project checks. Fix failures caused by the change. Report pre-existing failures distinctly, with actual output.
4. Optionally use collaboration subagents for independent tasks when available. Give each agent one task, target path, acceptance criteria, and verification requirements. Do not depend on named plugin agents, specific models, or any particular delegation API.
5. Before marking a task complete, review its diff for correctness, scope, tests, and maintainability. Use the `sdd-code-review` skill for phase-level review or material risk.
6. While the task remains `in-progress`, create `### Completion Evidence` if a
   legacy task lacks it, then replace its pending content using
   `shared/completion-evidence.md`:
   record the verification date, canonical tested source identity, permitted
   exact SDD exclusions and identity recheck, every exact command with working
   directory and exit status, every non-command tool or inspection,
   and the observable results satisfying the task's prospective `verification`.
   Apply the canonical source-identity procedure, permitted exclusion rule,
   and immediate recheck from that contract. For dirty work, capture the
   canonical manifest and content objects durably and record their digest; a
   path list or ordinary patch is insufficient. Do not paste a claim
   unsupported by output read in this session or a linked contemporaneous
   durable record.
7. Re-read the task section. Confirm the evidence is present, no pending marker
   remains, at least one command or tool/inspection row exists, every required
   verification behavior is covered, the source-identity recheck still matches
   the tested content, and every final required check passed.
   Only then set the task status to `complete`, check completed subtasks, and
   update frontmatter. A task with absent, pending, vague, or failing evidence
   stays non-complete.
8. Commit only when the user or repository policy calls for it.

## Escalate

Ask the user before destructive or production-impacting operations, when requirements are ambiguous, when implementation reveals unplanned scope, or after two failed attempts to resolve a blocking verification failure.

**Record escalation resolutions.** When the user answers an escalation with a choice that constrains future work — an ambiguity resolved, scope accepted or cut, an approach picked for a blocked task — record it in the decision ledger per `shared/decision-log.md` (collision check before appending; a collision is itself a stop). If the fresh answer collides with an accepted entry, use the ledger's **one-step supersession**: "this supersedes D-NNNN — confirm?" — don't make the user relitigate what they just decided. Scope the entry to the plan. Pure one-off dispositions ("retry it", "skip for now") are events, not decisions — don't log them.

## Output

For each completed task report files changed, verification commands with actual results, the populated completion-evidence section, status updates, and any deferred findings. Deferred review findings are tracked per `shared/review-artifacts.md` (plan tasks or `FU-NN` follow-ups) — never left only in conversation. Keep the plan artifact as the source of truth.
