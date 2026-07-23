---
name: sdd-decision-log
description: "Recording user decisions as durable truth in the decision ledger. Use whenever the user makes a design or architecture choice, defines a project concept or term, answers a design question, reverses an earlier decision, or when current work touches a topic the ledger may already govern — including plain conversation outside any sdd-planner skill."
---

# Decision Log — Capture and Collision Discipline

Before opening `shared/...`, follow symlinks in this loaded file's path, then derive `<plugin-root>` from `<plugin-root>/skills/<name>/SKILL.md`; fallback search roots are repository/user `.agents/` (including `$HOME/.agents/plugins/*/`), Codex `${CODEX_HOME:-$HOME/.codex}/plugins/cache/*/*/*/`, and runtime-configured skill roots. Accept only a root containing this skill, `shared/agent-runtime.md`, and the matching plugin manifest; never use the working directory. Read `<plugin-root>/shared/agent-runtime.md` first.

**Resource boundary:** Read the plugin, all `SKILL.md` files, and `shared/` resources in place. Never copy or symlink them into the working directory, target repository, or planning root. Only generated SDD outputs may be materialized from bundled resources.

The full convention (entry schema, lifecycle rules, collision procedure, distribution rules) lives in `<plugin-root>/shared/decision-log.md` — read it before your first ledger write of a session. This skill exists so decision moments *outside* the lifecycle skills still reach the ledger.

Resolve the ledger per `<plugin-root>/shared/decision-log.md` § Ledger location — `<planning-root>/Decisions/decisions.md` for an in-repo planning root, `<repo-root>/DECISIONS.md` when the planning root is external (decisions live with the repo they represent). Create it from `<plugin-root>/shared/templates/decision-log.md` if missing.

Before trusting or mutating the resolved ledger, run:

```bash
python3 <plugin-root>/scripts/sdd_decision_validate.py <resolved-ledger> --format json
```

Exit `1` means repair the reported structural findings before continuing; exit
`2` is an operational stop. Do not substitute manual YAML inspection. The
script's structural collision diagnostics are candidates for the human/model
judgment pass; inspect them even when exit status is `0`. They are never
authority to reconcile entries automatically.

## When the user just decided something

1. Recognize the moment: a stated choice between alternatives, a definition of a project term, an answer to a design question, or an explicit reversal. Status updates and task events are not decisions — the test is whether a future session would act differently for knowing it.
2. **Run the collision check first** (`shared/decision-log.md` § Collision Detection): grep the ledger for the new entry's tags, scope, and key nouns; apply the structural checks; judge survivors. On `contradicts`/`supersedes` → STOP and present both entries for the user to reconcile. Never auto-resolve, never pick by recency.
3. Append the entry (next sequential `D-NNNN`; use `decided_by: user` and `status: accepted` only if the user stated the choice, otherwise `decided_by: agent` and `status: proposed`) and update the ledger's `updated` date.
4. Rerun the deterministic validator. Correct a malformed write before continuing; never auto-resolve a collision diagnostic.
5. Mention the recording in one line (e.g., "Recorded as D-0007 in the decision ledger") — no ceremony.

## When about to act on a governed topic

Before drafting or implementing in an area the ledger may govern, validate the
ledger, then check `accepted` entries whose tags/scope match. They are
constraints: if the current ask contradicts one, surface the collision instead
of silently following either side.
