---
name: sdd-validate
description: "Validate SDD artifact structure, status, completion evidence, dependencies, identifiers, and decision-ledger consistency without modifying files. Use before implementation, completion, handoff, or CI; validate plan, check SDD integrity, audit completion evidence."
---

# Validate SDD Artifacts

## Resources

Before opening `shared/...`, follow symlinks in this loaded file's path, then
derive `<plugin-root>` from `<plugin-root>/skills/<name>/SKILL.md`; fallback
search roots are repository/user `.agents/` (including
`$HOME/.agents/plugins/*/`), Codex
`${CODEX_HOME:-$HOME/.codex}/plugins/cache/*/*/*/`, and runtime-configured skill
roots. Accept only a root containing this skill, `shared/agent-runtime.md`, and
the matching plugin manifest; never use the working directory. Then read
`<plugin-root>/shared/agent-runtime.md`,
`<plugin-root>/shared/path-resolution.md`,
`<plugin-root>/shared/frontmatter-schema.md`,
`<plugin-root>/shared/completion-evidence.md`, and
`<plugin-root>/shared/decision-log.md`, and
`<plugin-root>/shared/review-artifacts.md`.

**Read-only guarantee:** validation never edits, moves, creates, or deletes
artifacts and never changes status. Report exact findings for a lifecycle skill
or user-authorized repair to address.

## Scope

Validate the named artifact or, when asked for repository-wide validation, all
artifacts under the resolved planning root. Read complete plan README and phase
documents when validating any plan lifecycle state.

## Checks

### Structure and frontmatter

- YAML parses and required common/type-specific fields exist.
- Status values match `shared/frontmatter-schema.md`.
- Required template sections exist and are nonempty where the schema requires
  content.
- Plan phase `doc` paths, `related` links, and decision scopes resolve.
- Legacy status-subfolder layouts are invalid; report them without migration.

### Hierarchy, dependencies, and traceability

- Plan README phase ids/statuses match their phase documents.
- Task and phase `depends_on` ids resolve, are not self-referential, and form no
  cycle.
- Required requirements and acceptance criteria are numbered. `FR-NN`,
  `NFR-NN`, and `AC-NN` are unique within their owning spec; task and phase ids
  within their plan; `F-NN` and `FU-NN` within their review; and `D-NNNN`
  across the live decision ledger and archives. Citations resolve against the
  owning or explicitly related artifact rather than a repository-global id.
- Complete parent entities contain no incomplete child entity.

### Review artifacts

- Frontmatter finding status matches its Resolution Log disposition; an
  artifact is `resolved` only when every finding is terminal.
- Every deferred finding is tracked either by an existing plan task cited in
  its resolution or by a corresponding `FU-NN`. Every nonempty
  `followups[].tracked_in` value resolves to an existing plan task. Always
  report an empty `tracked_in` as floating; explicit user acceptance may permit
  the review's `resolved` status but does not suppress that finding.
- Review supersession links are bidirectional and resolve.

### Completion evidence

Apply `shared/completion-evidence.md` literally:

- Every task, phase, and plan has its required evidence section.
- A complete entity has fully conforming retrospective evidence: verification
  date; repository root and VCS kind; exact clean revision or canonical content
  snapshot digest and durable artifact; permitted exact exclusions;
  governing-intent digest; ignored/directory-input inventories; a successful
  immediate identity recheck; exact commands/tools; context/working directory; exit
  status or result; and specific observable evidence covering prospective
  verification.
- Every required final and aggregate check passed. Missing, unrun, vague,
  stale, or failing evidence makes a `complete` status invalid.
- Phase evidence covers every task and acceptance criterion. Plan evidence
  repeats exact task/phase evidence rollups and covers the plan deliverable;
  links alone do not satisfy the record.
- Non-complete entities may be pending or contain populated evidence awaiting
  validation.
- Historical complete artifacts without conforming evidence are reported as
  legacy evidence gaps; never infer or fabricate evidence.

### Decision ledger

- Required entry fields and allowed statuses are valid.
- Sequential ids are unique across the live ledger and archives.
- Supersession links are bidirectional and resolve.
- Accepted decisions scoped to an artifact are cited by that artifact.
- Every live-artifact citation to a `superseded` or `rejected` decision is
  reported as stale.
- Deterministic collisions are reported: conflicting answers to the same
  question, chosen options present in another entry's `rejected`, or divergent
  definitions of the same term with overlapping scope. Judgment-required
  potential conflicts are reported as questions, never auto-resolved.

## Output

Open with `Valid` or `Invalid`. For every finding include severity, artifact and
section/line, violated rule, and the exact required correction. Include the
files and checks inspected so absence claims have a search trail. A valid
result names the scope and confirms each check class; it is not a generic
“looks good.”
