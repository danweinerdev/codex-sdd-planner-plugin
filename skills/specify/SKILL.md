---
name: specify
description: "Write a requirements specification for a feature. Do NOT enter plan mode — this skill produces a spec artifact directly. write spec, specify requirements, requirements for"
---

# Write Requirements Specification

## Path Resolution
Read `shared/codex-runtime.md` to locate bundled resources, then read `shared/path-resolution.md` to resolve artifact and target-repository paths.

## When to Use
When you need to define the requirements for a feature before designing or implementing it. Produces a testable, reviewable specification.

## Process

1. **Gather Context**
   - If the user hasn't already specified it, ask what feature to specify
   - Use a Codex collaboration agent (if available) to gather context from existing artifacts and codebase
   - Review any related research or brainstorm documents

2. **Draft Specification**
   - Create `Specs/<FeatureName>/README.md` using `shared/templates/spec.md`
   - Write: overview, goals, non-goals, requirements (functional + non-functional), user stories, acceptance criteria, constraints, dependencies
   - When the spec captures an **external contract** (a third-party API, protocol, wire format, or another team's interface), pin the source: link the authoritative doc and record its version and as-of date in the spec. Downstream implementation is only allowed to derive external-contract behavior from this captured source — never from model memory — so the pin is load-bearing.
   - Set status to `draft`

3. **Review**
   - Set `status: review` when dispatching the reviewer
   - Perform an independent specification-review pass to review the specification
   - Address critical and major issues

4. **Present for Approval**
   - Show the user the review results and final spec
   - **Open questions gate approval.** Before setting `status: approved`, every remaining open question must be either resolved or explicitly marked **non-blocking** with a one-line rationale for why the requirements hold regardless of its answer. A question whose answer could change in-scope requirements blocks approval — leave the spec at `review` and name the question to the user. A "⚠️ pending confirmation" annotation is not a gate.
   - After findings are addressed and the user explicitly approves, set `status: approved`. If the user declines or defers, leave it at `review`.
   - Then re-read the frontmatter and confirm it parses as YAML and includes `title`, `type`, `status`, `created`, `updated`, `tags`, `related`.

## Output
```
Specs/<FeatureName>/README.md
```

## Document Structure
See `shared/templates/spec.md`:
- **Overview**: Feature purpose
- **Goals / Non-Goals**: Scope boundaries
- **Requirements**: Functional and non-functional
- **User Stories**: As a [user], I want to...
- **Acceptance Criteria**: Testable pass/fail criteria
- **Constraints / Dependencies / Open Questions**

## Context
- Orchestration: `shared/orchestration.md`
- Template: `shared/templates/spec.md`
- Schema: `shared/frontmatter-schema.md`
- Agents: a Codex collaboration agent (if available), an independent specification-review pass
