# Path Resolution

## Planning root

Artifacts (`Research/`, `Brainstorm/`, `Specs/`, `Designs/`, `Plans/`, `Retro/`, `Diagrams/`) are read from and written to the planning root.

1. Find `planning-config.json` in the current directory or its parents through the repository root.
2. If no config exists, use the repository root and treat `planningRoot` as `"."`.
3. If config exists, resolve `planningRoot` relative to the config's directory unless it is absolute. An absent value and `"."` mean the config directory.

## Plugin resources

Locate bundled resources as described in `shared/codex-runtime.md`. The `shared/` directory belongs to the installed plugin, never to the planning root.

## Target repository

Plans can target another repository:

1. Resolve `planning-config.json` `planMapping["<PlanName>"]` to a repository key.
2. Resolve `planning-config.local.json` `repositories.<key>.path`.
3. Verify that path exists.

If any part is missing, ask for the target directory. Never guess or clone.
