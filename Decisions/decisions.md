---
title: "Decision Ledger"
type: decision-log
status: active
created: 2026-07-18
updated: 2026-07-23
tags: [decisions]
related: []
decisions:
  - id: D-0001
    kind: decision
    status: accepted
    date: 2026-07-18
    decided_by: user
    statement: "Bundled shared resources must be resolved from the plugin installation root derived from the loaded skill or the runtime's standard skill locations, never relative to the working directory."
    rejected: ["Resolve shared paths relative to the working directory"]
    rationale: "Skills may be loaded from different host-specific locations, including OpenCode Agent Skills roots and Codex plugin caches, while the shared directory remains a sibling of the plugin's skills directory."
    confirmation: "Every SKILL.md bootstraps the plugin root before opening shared resources, and shared/agent-runtime.md lists and validates the supported discovery locations."
    scope: [skills, shared/agent-runtime.md]
    tags: [plugin-resources, path-resolution, runtime-neutral]
  - id: D-0002
    kind: decision
    status: accepted
    date: 2026-07-18
    decided_by: user
    statement: "SDD workflows must read the installed plugin, skills, and shared resources in place and must never copy or symlink bundled plugin material into a working directory, target repository, or planning root."
    rejected: ["Copy plugin resources into the workspace as a discovery or access workaround"]
    rationale: "Plugin material has host-specific installed locations and is workflow input, while the workspace should contain generated SDD outputs rather than duplicated runtime resources."
    confirmation: "Every SKILL.md states the resource boundary, shared/agent-runtime.md defines read-in-place behavior and failure handling, and setup forbids plugin-resource copies and symlinks."
    scope: [skills, shared/agent-runtime.md, shared/path-resolution.md]
    tags: [plugin-resources, workspace-boundary, read-in-place]
  - id: D-0003
    kind: decision
    status: accepted
    date: 2026-07-18
    decided_by: user
    statement: "Completed repository changes must be recorded in clean, scoped commits."
    rejected: ["Leave completed changes uncommitted", "Mix unrelated changes in one commit"]
    rationale: "Clean commits preserve reviewability and make completed work easy to trace or revert."
    confirmation: "At completion, inspect status and diff, commit only intended files with a repository-style message, and confirm the worktree is clean."
    scope: []
    tags: [git, commits, workflow]
  - id: D-0004
    kind: decision
    status: accepted
    date: 2026-07-21
    decided_by: user
    statement: "Every public sdd-planner skill name and installation directory uses the sdd- prefix, with no unprefixed compatibility aliases."
    rejected: ["Keep generic unprefixed skill names", "Use the longer sdd-planner- prefix"]
    rationale: "The sdd- prefix identifies ownership and prevents collisions in global skill discovery while remaining concise."
    confirmation: "Every skills/* directory and SKILL.md name starts with sdd-, and installed ~/.agents/skills links expose no legacy short-form sdd-planner names."
    scope: [skills, README.md]
    tags: [skill-names, namespace, installation]
  - id: D-0005
    kind: decision
    status: accepted
    date: 2026-07-21
    decided_by: user
    statement: "An SDD task, phase, or plan may not be marked complete until its artifact contains a populated completion-evidence section recording exactly what commands, tests, tools, or inspections ran and the observed results."
    rejected: ["Treat prospective verification criteria or checked subtasks as proof of completion", "Keep completion evidence only in conversation"]
    rationale: "Durable retrospective evidence makes completion auditable and gives execution trackers a concrete basis for closure instead of trusting status alone."
    confirmation: "shared/completion-evidence.md defines the required sections; lifecycle skills write and validate them before complete transitions; sdd-validate rejects missing, pending, stale, or failing evidence on complete entities."
    scope: [README.md, shared/completion-evidence.md, shared/frontmatter-schema.md, shared/templates/plan-readme.md, shared/templates/plan-phase.md, shared/agent-prompts/plan-reviewer.md, skills/sdd-plan, skills/sdd-implement, skills/sdd-debrief, skills/sdd-validate, skills/sdd-code-review]
    tags: [completion, verification, evidence, lifecycle]
  - id: D-0006
    kind: decision
    status: accepted
    date: 2026-07-21
    decided_by: user
    statement: "The sdd-planner public surface is a compact lifecycle core: diagram, excavate, retro, and simplify are removed; excavation becomes a research mode; broad tend is replaced by read-only deterministic sdd-validate."
    rejected: ["Keep all peripheral workflow skills in the core plugin", "Remove artifact validation together with tend"]
    rationale: "A smaller public surface reduces overlap and selection ambiguity while preserving the integrity checks required for status, evidence, dependency, identifier, and decision correctness."
    confirmation: "The manifest skills directory exposes exactly the documented core; removed skill paths and symlinks are absent; sdd-validate is read-only and runs the deterministic integrity checks."
    scope: [README.md, .codex-plugin/plugin.json, skills, shared/frontmatter-schema.md, shared/path-resolution.md, shared/templates/agents-md-full.md]
    tags: [skill-surface, compact-core, validation]
  - id: D-0007
    kind: decision
    status: accepted
    date: 2026-07-21
    decided_by: user
    statement: "Deterministic sdd-validate checks run through a versioned Python script using PyYAML; AI validation is reserved for semantic judgments that the script cannot establish."
    rejected: ["Perform every validation check by reading artifacts only in AI context", "Implement a partial YAML parser instead of using PyYAML"]
    rationale: "A scripted validator makes structural, reference, graph, and evidence-shape checks reproducible while retaining model judgment for whether content and evidence are semantically sufficient."
    confirmation: "The sdd-validate skill invokes the bundled validator first, its dependency on PyYAML is declared, and automated fixtures cover valid and invalid artifact graphs."
    scope: [skills/sdd-validate, scripts, tests]
    tags: [validation, python, pyyaml, deterministic-checks]
  - id: D-0008
    kind: decision
    status: accepted
    date: 2026-07-22
    decided_by: user
    statement: "SDD code-review lanes expose stable runtime-neutral dispatch identifiers that runtime adapters may map to named agents and models without making sdd-planner depend on those agents, models, or a delegation API."
    rejected: ["Embed OpenCode agent or model names in sdd-code-review", "Leave code-review lane dispatch labels implicit and unstable"]
    rationale: "Stable semantic identifiers preserve portable SDD workflows while allowing capable runtimes to select cost- and capability-appropriate workers deterministically."
    confirmation: "sdd-code-review and shared/review-lanes.md define the same exact lens-to-identifier mapping; tests enforce that mapping, runtime-neutral identifier text, and fresh-context/Mixed fallback language."
    scope: [skills/sdd-code-review, shared/review-lanes.md, shared/agent-runtime.md, README.md]
    tags: [code-review, dispatch, collaboration, runtime-neutral]
  - id: D-0009
    kind: decision
    status: accepted
    date: 2026-07-23
    decided_by: user-approved
    statement: "SDD code implementation dispatches use the stable runtime-neutral identifier implement_task, which runtime adapters may map to a dedicated implementer role with independently configurable model and effort while bounded-editor remains for mechanical edits."
    rejected: ["Route semantic code implementation through bounded-editor", "Embed OpenCode agent names or model identifiers in sdd-planner or sdd-beads"]
    rationale: "Separating semantic implementation from mechanical editing allows stronger reasoning for code changes without coupling portable SDD workflows to a runtime or overspending on simple text edits."
    confirmation: "sdd-implement emits implement_task without naming a runtime agent or model; runtime-adapter tests map it to implementer; model profile tests cover explicit selection and reasoner fallback."
    scope: [skills/sdd-implement, shared/agent-runtime.md, README.md]
    tags: [implementation, dispatch, collaboration, runtime-neutral, model-routing]
  - id: D-0010
    kind: decision
    status: accepted
    date: 2026-07-23
    decided_by: user
    statement: "Decision-ledger operations use a bundled deterministic validator for format and every safely machine-checkable invariant, while semantic collision judgment remains outside the script."
    rejected: ["Rely only on model inspection to validate decision-ledger structure", "Treat semantic contradiction judgments as deterministic"]
    rationale: "A focused validator catches malformed or inconsistent ledgers reproducibly before and after writes without pretending that differently worded decisions can be reconciled mechanically."
    confirmation: "The decision-log convention and both decision-writing skills invoke the bundled validator, and automated fixtures cover valid and invalid ledger states."
    scope: [shared/decision-log.md, skills/sdd-decide, skills/sdd-decision-log, scripts, tests]
    tags: [decision-log, validation, python, pyyaml, deterministic-checks]
---

# Decision Ledger

Machine-readable record of decided truths. The frontmatter `decisions[]` array is canonical.
