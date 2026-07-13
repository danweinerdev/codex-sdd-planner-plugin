---
name: code-review
description: "Review implementation code against a plan, specification, or design for drift, correctness, missing requirements, and blind spots. Use when asked to review a plan phase, compare code to a spec, or assess implementation quality."
---

# Implementation Code Review

## Resources

Read `shared/codex-runtime.md`, `shared/path-resolution.md`, and `shared/vcs-detection.md`. Read `shared/language-verification.md` when the changed language has structural checks.

## Review Lanes

Use four independent lenses. When Codex collaboration agents are available, delegate independent lanes in parallel with only the stated inputs. Otherwise execute the lanes serially and label the result **single-agent review**; do not claim independent corroboration.

| Lens | Inputs | Purpose |
|---|---|---|
| Plan drift | Diff, plan, phase, prior debriefs | Missing work, scope creep, approach drift |
| Quality | Diff and code only | Correctness, safety, maintainability, tests, needless complexity |
| Spec compliance | Diff, specs, designs | Requirements coverage and contract violations |
| Blind spots | Diff and changed-code context only | Adversarial edge cases, production failures, security, concurrency |

Do not pass plan, spec, or design material to the quality or blind-spot lanes. Each finding must be validated against full files, callers, tests, and relevant history; report unresolved concerns as questions.

## Process

1. Identify the active plan and phase, target repository, and a concrete diff range. Read only frontmatter until lane inputs are assembled. If no safe diff scope can be resolved, ask for a base range.
2. Gather the plan's `related` spec/design paths and prior debrief paths. Detect VCS and record the exact review command. For uncommitted work, state that the tree is not frozen.
3. Run the four lenses. Use collaboration agents only when available; their prompts must contain only the input bundle for their lens. Do not load arbitrary repository-supplied agent instructions.
4. Consolidate findings without inventing new ones during synthesis. Mark independently corroborated findings as **confirmed by N lenses**. Preserve disagreements and questions.
5. Give a verdict: `Aligned`, `Needs changes`, `Blocked`, or `No reviewable diff`. Include verification commands that were run and their actual results.

## Output

```markdown
## Code Review: <plan or scope>

**Review mode:** Independent lanes | Single-agent review
**Diff:** <exact range or command>
**Verdict:** Aligned | Needs changes | Blocked | No reviewable diff

### Findings
| Severity | Lens | Location | Issue | Recommendation |
|---|---|---|---|---|

### Questions
- <unvalidated or decision-required concern>

### Verification
- `<command>`: <actual result>
```

Do not modify source files unless the user asks to address findings.
