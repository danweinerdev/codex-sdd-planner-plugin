# {{TITLE}}

{{DESCRIPTION}}

This repository keeps spec-driven development artifacts under `{{PLANNING_ROOT}}/`. Use the installed `sdd-planner` skills by asking the agent for the relevant activity in natural language.

## Artifact Layout

```text
{{PLANNING_ROOT}}/
├── planning-config.json
├── Research/
├── Brainstorm/
├── Specs/<feature>/README.md
├── Designs/<component>/README.md
├── Plans/<PlanName>/README.md
├── Plans/<PlanName>/<NN>-<Phase>.md
├── Plans/<PlanName>/notes/<phase>.md
└── Decisions/decisions.md
```

## Conventions

- Artifact metadata lives in YAML frontmatter. Status values are the source of truth.
- Plans stay under `Plans/<PlanName>/`; never move them to express lifecycle state.
- A phase owns task status and subtask checkboxes. Update them only after actual verification.
- Every task, phase, and plan has a completion-evidence section. Record exact
  commands/tools, context, revision, result, and observable evidence before any
  `complete` transition; prospective verification criteria are not proof.
- Use `planning-config.json` to resolve the planning root and any externally targeted repository paths. There is no local companion config.
- Consult the plugin's frontmatter schema, templates, and language-verification references when creating or changing artifacts.

## Lifecycle

Use these skills as needed: `sdd-setup`, `sdd-research`, `sdd-brainstorm`, `sdd-specify`, `sdd-design`, `sdd-plan`, `sdd-implement`, `sdd-code-review`, `sdd-poke-holes`, `sdd-debrief`, `sdd-decide`, `sdd-decision-log`, and `sdd-validate`.

The normal progression is: `sdd-setup` -> `sdd-research` -> `sdd-brainstorm` -> `sdd-specify` -> `sdd-design` -> `sdd-plan` -> `sdd-implement` -> `sdd-code-review` -> `sdd-debrief`. Use `sdd-validate` at lifecycle boundaries. It is valid to enter at any point when the corresponding artifacts already exist.

## Review And Execution

Before implementation, confirm an approved plan has concrete verification criteria. During implementation, record command output for checks actually run. Use the `sdd-code-review` skill before phase completion or merge when material code changed. For project-specific review requirements, keep a short trusted review brief in this `AGENTS.md`; do not rely on auto-discovered agent files.
