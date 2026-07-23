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

Before analyzing artifacts in model context, run the bundled deterministic
validator from the target repository root:

```bash
python3 <plugin-root>/scripts/sdd_validate.py --format json
```

Pass `--scope <planning-root-relative-path-or-artifact-name>` when the user
named a narrower scope. PyYAML is a declared plugin dependency in
`<plugin-root>/requirements.txt`; if it is unavailable, report the validator's
dependency error and stop rather than silently replacing deterministic checks
with model judgment. Exit `0` means scripted checks passed, exit `1` means the
JSON diagnostics are authoritative findings, and exit `2` means validation
could not run. Never execute artifact-recorded evidence commands as part of
validation.

For a direct decision-ledger write or focused ledger audit,
`scripts/sdd_decision_validate.py <resolved-ledger> --format json` provides the
stricter standalone format, archive, supersession, structural-candidate, and
Git-backed immutability checks required by `shared/decision-log.md`. The full
validator remains authoritative for cross-artifact scope resolution, citations,
and related-graph checks.

Identity mode defaults to `auto`, which performs current target-worktree and
governing-projection checks for every populated evidence section. Use the
equivalent explicit `--identity-mode current` immediately before a completion
transition or tracker closure. Use `--identity-mode historical` only for a
confirmed historical audit where later legitimate work makes current-source
comparison inappropriate.

**Read-only guarantee:** validation never edits, moves, creates, or deletes
artifacts and never changes status. Report exact findings for a lifecycle skill
or user-authorized repair to address.

## Scope

Validate the named artifact or, when asked for repository-wide validation, all
artifacts under the resolved planning root. Read complete plan README and phase
documents when validating any plan lifecycle state.

## Checks

The script owns machine-decidable structure, schema, path, identifier, graph,
review-state, decision-link, durable-digest, and evidence-shape checks below.
Do not repeat those checks manually or reinterpret a scripted failure. After it
runs, use model analysis only for semantic sufficiency: whether prose has real
content, evidence proves the cited behavior and acceptance criteria, aggregate
evidence covers the deliverable, and differently worded decisions potentially
conflict. Merge those semantic findings with the script diagnostics in the
required output format.

For every scoped spec, design, or plan, resolve its explicit `related` graph and
perform a cross-artifact semantic reconciliation after the script passes its
citation matrix checks:

- Compare each `FR-NN`, `NFR-NN`, constraint, and accepted decision in the spec
  with the linked design. Report omitted behavior, incompatible contracts, and
  design choices that exceed or narrow approved scope.
- Compare the linked design with plan phases, task boundaries, dependencies,
  traps, and verification. Report architecture with no implementation task,
  tasks that contradict the design, and verification that cannot prove the
  governing `AC-NN` behavior.
- Compare the plan directly back to the spec so a shared design omission cannot
  make both downstream artifacts appear mutually consistent.
- Actively test the unhappy paths named by the governing artifacts: null/empty
  boundaries, ownership and cleanup, errors, concurrency, retries/timeouts, and
  cross-tenant or security boundaries where applicable.

The script proves citation presence, not semantic conformance. Never report the
artifacts reconciled merely because every identifier appears somewhere.

### Structure and frontmatter

- YAML parses and required common/type-specific fields exist.
- Status values match `shared/frontmatter-schema.md`.
- Required template sections exist with the exact H2/H3 names consumed by the
  validator. The scripted check proves heading presence; the semantic pass
  separately rejects empty or placeholder-only required content.
- Plan phase `doc` paths, `related` links, and decision scopes resolve.
- Legacy status-subfolder layouts are invalid; report them without migration.

### Hierarchy, dependencies, and traceability

- Plan README phase ids/statuses match their phase documents.
- Every phase document is `type: phase`, matches its plan entry's title/id/status
  and plan backlink, lives under that plan, and is listed exactly once.
- Task and phase `depends_on` ids resolve, are not self-referential, and form no
  cycle.
- Required requirements and acceptance criteria are numbered. `FR-NN`,
  `NFR-NN`, and `AC-NN` are unique within their owning spec; task and phase ids
  within their plan; `F-NN` and `FU-NN` within their review; and `D-NNNN`
  across the live decision ledger and archives. Citations resolve against the
  owning or explicitly related artifact rather than a repository-global id.
- Complete parent entities contain no incomplete child entity.
- When Git HEAD contains the prior artifact, spec requirement ids and plan
  phase/task ids remain present in both index and worktree; deletion, rename,
  type substitution, or hidden staged removal is invalid.
- Approved/implemented specs and designs and approved/active/complete plans
  contain no blocking Open Questions; retained bullets use the exact
  `**non-blocking** — <rationale>` form.

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
- Dirty Git snapshot manifests match current changed, nonignored untracked,
  explicitly inventoried ignored, and directory inputs byte-for-byte and by
  mode; staged/index content matches the tested worktree.
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
- Deterministic structural collision candidates are reported: differing answers
  to the same question, chosen options present in another entry's `rejected`,
  or divergent definitions of the same term with overlapping scope. Candidate
  diagnostics are nonfatal and require model/user judgment; report potential
  conflicts as questions and never auto-resolve them.

## Output

Open with `Valid` or `Invalid`. For every finding include severity, artifact and
section/line, violated rule, and the exact required correction. Include the
files and checks inspected so absence claims have a search trail. A valid
result names the scope and confirms each check class; it is not a generic
“looks good.”
