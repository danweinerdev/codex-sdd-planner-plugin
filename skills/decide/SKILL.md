---
name: decide
description: "Record, look up, or reconcile entries in the decision ledger — the persistent log of decided truths. record decision, log this decision, what did we decide, decision ledger, supersede decision"
---

# Decision Ledger Operations

## Path Resolution
Read `shared/agent-runtime.md` to locate bundled resources, then read `shared/path-resolution.md` to resolve artifact and target-repository paths.

## When to Use
- Explicitly record a decision, concept definition, or answered design question as durable truth
- Look up what was decided about a topic ("what did we decide about auth?")
- Reconcile a collision — supersede an old decision with a new one
- Backfill a decision the automatic capture missed

The convention — entry schema, lifecycle rules, collision procedure — is defined in `shared/decision-log.md` (single source of truth). Read it before operating on the ledger.

## Operations

| Ask | Operation |
|---|---|
| "record/log this decision: <statement>" | Record (default) |
| "list decisions [for tag/scope]" | List |
| "what did we decide about <term>?" | Search |
| "show D-NNNN" | Show |
| "accept D-NNNN" | Accept |
| "supersede D-NNNN" | Supersede |

## Process

### 0. Resolve the ledger
Resolve the ledger per `shared/decision-log.md` § Ledger location: `<planning-root>/Decisions/decisions.md` when the planning root is inside the repo; `<repo-root>/DECISIONS.md` when the planning root is external (decisions live with the repo they represent — resolve the repo via `shared/path-resolution.md`). If missing, create it from `shared/templates/decision-log.md` (and `mkdir -p` any needed directory) before proceeding.

### Record (default)
1. Draft the entry per the schema in `shared/decision-log.md`: next sequential `D-NNNN`, `kind`, `statement` (one standalone sentence), `rationale`, and — pull these from the conversation or ask briefly — `rejected[]` alternatives, `scope`, `tags`. `decided_by: user` and `status: accepted` only when the user actually made the choice; an agent-inferred decision is `status: proposed`.
2. **Run the collision check** (`shared/decision-log.md` § Collision Detection) before appending. On `contradicts`/`supersedes`, STOP and present both entries; the user chooses supersede / keep-old / both-hold-with-narrowed-scope. Never auto-resolve.
3. Show the drafted entry to the user in-flow, append it to `decisions[]`, update the ledger's `updated` date, and re-read the frontmatter to confirm it parses as YAML.

### List / Search / Show
Read the ledger frontmatter only (frontmatter-first). Present matching entries compactly: `id — status — statement (date)`. For `show`, include the full entry plus any `## D-NNNN` body section. For lookups phrased as questions ("what did we decide about X?"), answer with the matching `statement`s and cite the ids — the statement IS the answer.

### Accept
Promoting a `proposed` entry is an **append-equivalent event** (`shared/decision-log.md` lifecycle rules): only the user can accept, and the full collision check re-runs first — entries accepted since the proposal was logged may collide with it. On a clean check, set `status: accepted`, update the entry's `date` and the ledger's `updated` date. On a collision, stop and run the reconciliation menu.

### Supersede
1. Read the target entry. If it isn't `accepted`, tell the user (rejected/superseded entries need no supersession; proposed entries can simply be edited — they aren't immutable yet).
2. Draft the replacement entry with `supersedes: D-NNNN`; confirm with the user.
3. Append the new entry; on the old entry set `status: superseded` and `superseded_by: <new id>` — touching nothing else in it.
4. Run the **supersession cascade** from `shared/decision-log.md`: grep `Specs/`, `Designs/`, `Plans/` for citations of the superseded entry and report possibly-stale artifacts. Don't rewrite them unasked.

## Output
Appends to (or creates) `Decisions/decisions.md`. Never deletes or rewrites accepted entries — status and supersession links are the only permitted mutations.

## Context
- Convention (single source of truth): `shared/decision-log.md`
- Template: `shared/templates/decision-log.md`
- Schema: `shared/frontmatter-schema.md`
- Orchestration: `shared/orchestration.md`
- Autonomy: `shared/autonomy.md` — writing an entry is autonomous; resolving a collision always stops for the user
