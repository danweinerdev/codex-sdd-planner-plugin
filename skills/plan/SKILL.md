---
name: plan
description: "Create or expand a structured implementation plan with phases, tasks, subtasks, and verification criteria. Re-running on an existing plan deepens it — adds tasks, fills gaps, refines subtasks. Do NOT enter plan mode — this skill produces plan artifacts directly. create a plan, plan this, implementation plan, expand plan, add detail, break down, breakdown, expand phase"
---

# Create or Expand an Implementation Plan

## Path Resolution
Before opening `shared/...`, follow symlinks in this loaded file's path, then derive `<plugin-root>` from `<plugin-root>/skills/<name>/SKILL.md`; fallback search roots are repository/user `.agents/` (including `$HOME/.agents/plugins/*/`), Codex `${CODEX_HOME:-$HOME/.codex}/plugins/cache/*/*/*/`, and runtime-configured skill roots. Accept only a root containing this skill, `shared/agent-runtime.md`, and the matching plugin manifest; never use the working directory. Then read `<plugin-root>/shared/agent-runtime.md` and `<plugin-root>/shared/path-resolution.md`.

**Resource boundary:** Read the plugin, all `SKILL.md` files, and `shared/` resources in place. Never copy or symlink them into the working directory, target repository, or planning root. Only generated SDD outputs may be materialized from bundled resources.

## When to Use
- When you need to break down a feature, project, or initiative into an actionable plan with phases, tasks, subtasks, and verification criteria.
- When you want to deepen an existing plan — add tasks, fill in missing verification, expand subtask checklists, or refine acceptance criteria as you learn more.

Both cases run through the same process below. The skill detects whether the named plan already exists and switches into **Revise mode** automatically. High-risk plans can optionally be **rehearsed** — dry-run in a scratch worktree to shake out plan bugs — before approval (step 6).

## Process

### 1. Determine Mode (Create vs Revise)

- If the user hasn't already specified it, ask what they want to plan (feature name, scope, goals).
- If `Plans/<PlanName>/README.md` already exists, switch to **Revise mode** — load the README and only the phase docs in scope for this revision into context (delegate a full-plan sweep to the researcher step instead of reading every phase doc yourself) and proceed to step 2.
- Otherwise, you're in **Create mode** — proceed to step 2 with no existing plan to load.

If the existing plan's `status` is `complete` or `archived`, confirm with the user before revising it — those plans are usually frozen.

### 2. Gather Context (delegated to a collaboration subagent (if available))

Use a collaboration subagent (if available), rendering `shared/agent-prompts/researcher.md` with the plan topic and resolved paths, and ask it to return a **structured** summary, not freeform notes:

- **Relevant requirements** — spec items under `Specs/` that this plan should cover
- **Architectural constraints** — design decisions in `Designs/`, component boundaries, interfaces, contracts that constrain implementation
- **Background** — research, brainstorms, retros bearing on this work
- **Related plans** — other plans in `Plans/` that touch the same area (filter by `status` — usually `active`, `approved`, and plans completed within roughly the last three months; tell the researcher explicitly to include the latter, since it skips `complete` plans by default)
- **Existing code** — implementations already present in the target repo that this plan would extend, modify, or replace
- **Current coverage and gaps** — in Revise mode, what the existing tasks and subtasks already address, and what's missing, vague, or contradicted by the latest specs/designs. In Create mode, this comes through as "which spec requirements have no plan covering them yet."

Use this structured summary as the input to step 3 — every drafting decision should trace back to something the researcher surfaced.

### 3. Draft Plan Structure

**Create mode:**
- Determine the plan name (PascalCase, no spaces).
- Break work into phases with clear deliverables — typically 3-7 for a substantial feature. A small feature may legitimately be a single phase; never pad with filler phases.
- Each phase gets 2-6 tasks.
- Identify dependencies between phases.

**Revise mode:**
- Review the existing phase list against the researcher's gap analysis.
- Identify: new tasks to add, existing tasks that need refinement (vague verification, missing subtasks, outdated notes), missing phases.
- **Preserve completed work.** Never delete or rewrite tasks that are already `complete` or referenced in a phase debrief under `notes/`. Refinements to completed tasks should be additive (new acceptance criteria, follow-up tasks) or noted as future work.
- Preserve existing task IDs and ordering. Append new tasks with the next available ID in their phase.

**Both modes:**
- **Every task must have a `verification` field** — a specific answer to "how do we know this work is good and complete?" that names specific behaviors to cover (e.g., "parser handles valid, malformed, and empty input", "endpoint returns 200 with valid payload and 400 with missing fields"). Vague criteria like "works correctly" or test counts are not acceptable — verification means each new or changed behavior has a corresponding check. Wherever the check is commandable, `verification` also names the exact command to run and the expected observable output (e.g., `cargo test auth::` — 14 tests pass, including the new refresh-expiry case), not just prose criteria. Prose-only criteria are acceptable only when no command can observe the behavior. "Works correctly" is never acceptable. In Revise mode, audit existing tasks and add `verification` to any that lack it. Where a task satisfies a spec acceptance criterion or requirement, its `verification` (or body section) cites the `AC-NN`/`FR-NN` id (`shared/frontmatter-schema.md` § Stable Identifiers) — phase-level Acceptance Criteria likewise cite the spec ids they roll up.
- **Include structural verification:** Read `shared/language-verification.md` and detect the target project language. Include the language-appropriate structural checks (sanitizers, static analysis, type checking) in verification fields where relevant — either per-task or as a dedicated verification task in each phase.
- **Gated scope.** A task whose correctness depends on an unanswered question only an external party can answer (the user, a stakeholder, a vendor, another team) must NOT be created provisionally. A "⚠️ pending confirmation" note is not a gate — a model will implement past it. Instead: either cut the work from scope, or create the phase with `status: blocked` naming the open question in the phase doc, and record the question in the plan README's Open Questions. A plan cannot move to `approved` while any in-scope task is gated on an unanswered external question.
- Present the structure (phases, tasks, refinements) to the user for feedback before writing files.

### 4. Write Plan Files

**Create mode:**
- Create `Plans/<PlanName>/README.md` using `shared/templates/plan-readme.md` with `status: draft`.
- Create numbered phase docs using `shared/templates/plan-phase.md`.
- Create `Plans/<PlanName>/notes/` directory for future debriefs. Drop a `.gitkeep` (or VCS-equivalent placeholder) inside so the empty directory survives cloning.
- Populate frontmatter with all phase/task metadata.

**Revise mode:**
- Update the existing README and phase doc frontmatter (`updated` date, new phase/task entries, refined `verification`).
- Create new phase files only when new phases are introduced.
- Leave existing `notes/` debriefs untouched.

**Both modes — body content depth is mandatory:**

For each task, write a `## <ID>: Task Title` section that includes:
- **`### Subtasks`** — a checklist (`- [ ]`) of the concrete implementation steps the implementer will work through. Not "implement X" — the actual steps a person would tick off (e.g., "add migration", "wire the handler", "cover the empty-input case in tests").
- **`### Notes`** — implementation guidance, edge cases, references to specific design sections, gotchas the researcher surfaced. If a task can't be broken into subtasks because it depends on research the implementer will do, say that explicitly here — don't leave the section blank.
- **`### Trap` (optional)** — for any task with a known tempting-but-wrong shortcut, name the shortcut and why it's wrong (e.g., "You will want to mock the clock here — don't; the race being tested lives in the real timer path."). Traps are written for a hasty model reading the task in isolation. Don't invent traps for tasks that have none.

Plus:
- Phase-level **Acceptance Criteria** as a checklist.
- Plan README sections: **Overview**, **Architecture** (with Mermaid diagrams where structure helps — prefer `graph TD` / `flowchart LR` over ASCII art), **Key Decisions**, **Dependencies**, and **Open Questions** (only when gated scope produced any — see step 3).

Shallow tasks with no subtasks or notes are not acceptable output — they're the failure mode this skill exists to prevent.

### 5. Review

- Render `shared/agent-prompts/plan-reviewer.md` (substitute the plan path and resolved paths) and dispatch it as a collaboration subagent in a fresh context that does not inherit the primary conversation. If collaboration is unavailable, perform the review yourself following that prompt and label it **self-review**.
- Address any issues raised by the reviewer.

### 6. Rehearse (optional dry run)

- Offer rehearsal when the plan is high-risk: multiple phases touching unfamiliar code, external API integration, data migrations, or the user asks for it. Otherwise skip this step silently.
- **Mechanics:** create a scratch git worktree of the target repo (or a full copy for non-git targets) — never rehearse against the live tree. Use an implementation agent when available to execute the plan's tasks literally, wave by wave, with the same evidence rules as the Implement skill (verification output pasted, STOP on plan-vs-reality mismatch).
- **The product is plan bugs, not code:** wrong file paths, impossible task order, missing prerequisites, underspecified tasks, verification commands that don't run as written, traps that were missed. Collect them, discard the scratch tree and all code, and fix the plan before it moves to `approved`.
- **Cost:** rehearsal roughly doubles the implementation spend for the rehearsed scope — that's why it's opt-in and aimed at high-risk plans.

### 7. Approve

- Before setting `status: approved`, confirm no in-scope work is gated on an unanswered external question — blocking questions must be resolved or the affected phase marked `blocked`.
- Once review passes (and any rehearsal findings are fixed):
  - **Create mode:** update the plan README frontmatter `status` to `approved`.
  - **Revise mode:** if `status` is `draft`, set it to `approved` once the review passes (same as Create mode — a re-run on a never-approved plan must not strand it in `draft`); otherwise leave `status` as-is.
- Then re-read the frontmatter and confirm it parses as YAML and includes `title`, `type`, `status`, `created`, `updated`, `tags`, `related`.
- **Record decisions**: after approval, record each user-resolved open question and each Key Decision the user actually made (not ones merely drafted for them) in the decision ledger per `shared/decision-log.md` — collision check before each append; a collision stops for the user. Scope entries to `Plans/<PlanName>` (or to the governing spec/design when the decision really lives there), and **cite each new entry's id inline** in the plan's Key Decisions section (e.g., "(D-0012)").

### 8. Hand Off to an Execution Tracker (optional capability hook)

After approval and decision recording are complete, inspect the skills exposed
by the current runtime. If `sdd-beads-publish` is available, invoke that skill
for the approved plan path. This is a capability handoff, not a bundled
dependency: do not search for, install, vendor, or copy the `sdd-beads` plugin,
and do not issue ad-hoc `bd` commands in place of its workflow.

The handoff applies in both Create and Revise mode so an approved plan revision
refreshes the existing Beads projection by stable SDD identity. The
`sdd-beads-publish` skill owns workspace detection and idempotent publication.
If it reports that Beads is unavailable, uninitialized, conflicted, or failed,
leave the approved SDD plan unchanged and report the handoff result explicitly;
never roll back approval and never claim that Beads was synchronized.

If `sdd-beads-publish` is not exposed by the runtime, skip this step silently.
The Plan skill must remain fully functional as a standalone SDD workflow.

## Output
```
Plans/<PlanName>/
├── README.md              # Plan overview with phases in frontmatter
├── 01-Phase-Name.md       # Phase 1 with tasks in frontmatter, subtasks + notes in body
├── 02-Phase-Name.md       # Phase 2
├── ...
└── notes/                 # Empty (Create) or pre-existing debriefs (Revise)
```

Plan lifecycle (`draft` → `approved` → `active` → `complete`) is tracked in the README frontmatter `status` field. The plan directory stays put.

When the optional `sdd-beads-publish` capability is available, an approved
plan is also projected into Beads after the SDD artifacts and decision records
are finalized. That projection is operational coordination state; it does not
replace this plan as the source of truth.

## Document Structure

### README.md
See `shared/frontmatter-schema.md` for the plan frontmatter schema. Body contains:
- **Overview**: What the plan delivers and why
- **Architecture**: High-level technical approach, with Mermaid diagrams
- **Key Decisions**: Major choices and rationale
- **Dependencies**: External prerequisites
- **Open Questions**: Unanswered external questions gating `blocked` phases (omit when there are none)

### Phase Docs
See `shared/frontmatter-schema.md` for the phase frontmatter schema. Body contains:
- **Overview**: What the phase delivers
- **Task sections**: Each headed by task ID (e.g., `## 1.1: Task Title`) with:
  - `### Subtasks` — checklist of concrete implementation steps
  - `### Notes` — implementation guidance, edge cases, design references
  - `### Trap` — optional; the known tempting-but-wrong shortcut for this task and why it's wrong (omit when a task has none)
- **Acceptance Criteria**: Phase-level completion criteria as a checklist

## Context
- Orchestration: `shared/orchestration.md`
- Templates: `shared/templates/plan-readme.md`, `shared/templates/plan-phase.md`
- Schema: `shared/frontmatter-schema.md`
- Existing plans: `Plans/` (status in each plan's `README.md` frontmatter)
- Related specs: `Specs/`
- Related designs: `Designs/`
- Agent prompts: `shared/agent-prompts/researcher.md`, `shared/agent-prompts/plan-reviewer.md`; an implementation agent (if available) (rehearsal only)
