# Codex Runtime Conventions

This plugin provides skills, not slash commands or plugin-defined subagent types. A skill is selected from its description when the user asks for its workflow in natural language.

## Plugin resources

The plugin root is the directory containing `skills/` and `shared/`. When a skill needs a bundled template or reference, resolve it relative to the loaded skill's path: `<plugin-root>/skills/<skill-name>/SKILL.md`. Read the needed file under `<plugin-root>/shared/`; never look in Claude caches or `.claude-plugin` directories.

If the runtime does not expose the loaded skill path, search for the unique sibling pair `skills/<skill-name>/SKILL.md` and `shared/frontmatter-schema.md` in the available plugin directories. Do not select a version by cache ordering.

## Delegation

Use Codex's collaboration agents only when they are available and a task is independent enough to benefit from parallel work. Plugin-defined agent names, models, tool allowlists, and Claude's `Task` interface do not exist in Codex. A skill must remain correct when performed by the primary agent alone.

## Project guidance

Use `AGENTS.md` for optional repository-level guidance. Do not create, update, or discover `CLAUDE.md`, `.claude/`, or `~/.claude/` paths.
