# Quality Review Output Format — Canonical Vocabulary

This file is the single source of truth for quality-review vocabulary: severity terms, lenses, validation discipline, and required evidence. It does not mandate one report shape; the Code Review skill and per-task findings may use different shapes while preserving this vocabulary.

Reference this file from `shared/templates/quality-scan-prompt.md` and `shared/templates/per-task-findings.md`. Treat it as a contract.

## Severity vocabulary

- **Critical** — Correctness or safety defect that can hit production: data loss, security hole, obvious crash. Must-fix before the change is accepted.
- **Major** — Defect that will cause bugs, brittleness, or substantial maintenance pain soon.
- **Minor** — Cleanup, clarity, small risk reduction.
- **Question** — Suspicion you couldn't confirm after validation. Surface so the orchestrator or user can decide. A false-positive at Critical or Major severity is worse than no finding; downgrade to Question rather than report a defect you couldn't validate.

**Severity reflects impact, not fix cost.** Never downscope a finding by estimating how long it would take a human to fix. Agents are not constrained by human development timelines. The right fix is right; surface it at its true severity and let the user decide.

## Lens vocabulary

Every finding is tagged with exactly one lens.

- **Correctness** — logic bugs, off-by-one, inverted conditions, concurrency issues, resource leaks, unhandled-but-reachable error paths, incorrect library/API usage.
- **Safety** — input validation gaps at trust boundaries, injection surfaces (SQL, shell, HTML, log), unsafe defaults, secrets/credentials in code, unchecked deserialization, path traversal, SSRF.
- **Maintainability** — functions doing too many things, deep nesting, duplication, misleading names, stale or contradicting comments, magic numbers/strings without context.
- **Testing** — new or changed behavior with no corresponding test, tests that assert the wrong thing, disabled or skipped tests without explanation, mocked dependencies where an integration test would be truthful.
- **Over-Engineering** — abstractions with one implementation and no realistic second, configuration for things that never change, pass-through wrappers, speculative extension points, dead code (unused imports, unreachable branches, commented-out blocks).

## Validation discipline (non-negotiable)

**Diffs lie by omission.** Before writing any finding, verify it against the actual files:

- **Read the full file.** The hunk may be surrounded by code that already addresses your concern.
- **Check the calling context.** Before claiming "this function doesn't handle null", grep for every caller and confirm null is reachable. Before claiming "this parameter is unused", check whether a subclass or wrapper uses it.
- **Check sibling files.** Before claiming "this module has no tests", glob for `test_*.py`, `*_test.go`, `*.test.ts` (or the project's convention) near the file.
- **Check type/interface definitions.** Before claiming a type is wrong, read where the type is defined and who else uses it.
- **Run the tools.** If the repo has linters, type checkers, or tests already configured (`Makefile`, `package.json` scripts, `pyproject.toml`), a quick run can confirm or kill a suspicion faster than reasoning about it.

If after validation you still can't confirm a finding, downgrade to **Question** rather than reporting a defect.

## What every finding must cite

Regardless of report shape (sectioned or table):

1. **Location** — `file.ext:line` (or `file.ext:line-range`). Required.
2. **Concrete description** — what is wrong, in one sentence. No vague concerns.
3. **Validation evidence** — what you read or ran to confirm it. File paths, grep targets, command outputs. This is how the user (and the orchestrator's synthesis step) distinguishes a confirmed finding from an unvalidated suspicion.

A finding without all three is a Question, not a finding.

## Recommendation block

Every report ends with a one-paragraph recommendation, calibrated to the severity of the findings:

- **block** — Critical findings present; do not accept until fixed.
- **fix-then-accept** — Major findings present; send back for a follow-up commit.
- **accept-with-followups** — Only Minor/Question findings; accept and capture the cleanup as a follow-up item.
- **accept** — No findings or only Questions that the orchestrator can resolve.

## What this file does NOT mandate

- The **shape** of the report (sectioned vs table) — callsites pick.
- The **wrapper** around findings (`Quality Report — <repo>` vs nothing) — callsites pick.
- Per-finding extra fields (e.g., the agent's default sectioned format includes `Risk of fix:` and `Recommendation:` lines per finding; the table form folds these into the Finding cell or omits them) — callsites pick.

Callsites that diverge from the vocabulary or validation discipline are violating the contract. Callsites that pick a different shape are not.
