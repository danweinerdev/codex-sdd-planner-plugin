## Spec-Driven Development

Planning artifacts live at `{{PLANNING_ROOT}}/`, configured by `planning-config.json`. Use the installed `sdd-planner` skills for research, specifications, designs, plans, implementation, review, debriefs, and validation.

Keep artifact status in YAML frontmatter. Update task status and subtask checklists only after verification commands have actually run and the task's completion-evidence section records the exact commands/tools, context, revision, result, and observable evidence. Phase and plan completion require their aggregate evidence sections under the same rule. Before implementation, read the active plan and phase; after material changes, run the `sdd-code-review` skill.
