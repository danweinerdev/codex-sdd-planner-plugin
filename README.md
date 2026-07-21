# SDD Planner Skills

`sdd-planner` is a runtime-neutral agent-skills plugin for spec-driven development. It creates and maintains Markdown planning artifacts with YAML frontmatter for research, specifications, designs, implementation plans, code review, debriefs, and validation.

Every capability is a plain `SKILL.md` skill with shared resources under `shared/` — no slash commands, named subagent types, runtime hooks, or model-specific instructions — so it works in any agent runtime that discovers `SKILL.md` skills, with any model. Public skill names use the `sdd-` prefix (`sdd-plan`, `sdd-implement`, `sdd-code-review`, and so on) to avoid collisions in global skill directories (D-0004):

- **OpenCode**: point a skills discovery path at this repository (for example `ln -s <this-repo> ~/.agents`, so the skills resolve as `~/.agents/skills/<name>/SKILL.md`), or mount it there in a container.
- **Codex**: install via the `codex-marketplace` repository, then install `codex-sdd-planner` from it. Start a new thread after installation so the skills are available.
- Any other runtime that loads the `.agents/skills` convention or directory-sourced skills works the same way.

Ask your agent for a workflow naturally: "set up spec-driven planning in this repository", "write a specification for this feature", or "review this implementation against the active plan."

Planning artifacts live in the root configured by `planning-config.json`. The plugin uses `AGENTS.md` for optional repository guidance and does not create tool-specific files or launchers.

Tasks, phases, and plans carry durable completion-evidence sections recording
the exact commands, tools, context, revision, and observed results used to
justify each `complete` transition (D-0005).

The compact core exposes: `sdd-setup`, `sdd-research`, `sdd-brainstorm`,
`sdd-specify`, `sdd-design`, `sdd-plan`, `sdd-implement`, `sdd-code-review`,
`sdd-poke-holes`, `sdd-debrief`, `sdd-decide`, `sdd-decision-log`, and
`sdd-validate` (D-0006). Codebase excavation is a mode of `sdd-research`;
diagramming, retrospectives, and generic simplification are outside the core.

After plan approval, the `sdd-plan` skill conditionally hands the approved artifact to
the independently installed `sdd-beads-publish` skill when that skill is
available. The integration is capability-detected: `sdd-planner` has no hard
dependency on Beads or the `sdd-beads` plugin, and an unavailable Beads
workspace leaves the approved SDD plan unchanged.
