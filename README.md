# Codex SDD Planner

`codex-sdd-planner` is a Codex plugin for spec-driven development. It creates and maintains Markdown planning artifacts with YAML frontmatter for research, specifications, designs, implementation plans, code review, debriefs, and retrospectives.

The plugin is distributed through the `codex-marketplace` repository. Install that marketplace, then install `codex-sdd-planner` from it. Start a new Codex thread after installation so the skills are available.

Ask Codex for a workflow naturally: “set up spec-driven planning in this repository”, “write a specification for this feature”, or “review this implementation against the active plan.”

Planning artifacts live in the root configured by `planning-config.json`. The plugin uses `AGENTS.md` for optional repository guidance and does not create Claude-specific files or launchers.
