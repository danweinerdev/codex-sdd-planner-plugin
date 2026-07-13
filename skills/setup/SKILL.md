---
name: setup
description: "Set up spec-driven planning in a repository by creating planning-config.json, artifact directories, ignore entries, and optional AGENTS.md guidance. Use when asked to initialize or configure planning for a repository or worktree."
---

# Configure Spec-Driven Planning

## Resources

Read `shared/codex-runtime.md`, `shared/path-resolution.md`, `shared/vcs-detection.md`, `shared/templates/agents-md-full.md`, and `shared/templates/agents-md-snippet.md`.

## Process

1. Determine the target directory. Use the user-provided path verbatim where possible; otherwise use the current directory. Stop for a bare git repository.
2. Determine `planningRoot`: explicit user value, existing `planning-config.json`, inherited worktree value, then `"."`. Preserve the chosen value exactly in config; resolve relative paths only for filesystem operations.
3. Write or preserve `<target>/planning-config.json`. Include optional `dashboard`, `title`, and `description` only when requested.
4. Create missing planning directories: `Plans/`, `Research/`, `Brainstorm/`, `Specs/`, `Designs/`, `Retro/`, and `Diagrams/`.
5. For Git or Perforce, ensure the appropriate ignore file contains `Dashboard/` and `planning-config.local.json` without duplicating entries.
6. Offer, but do not unprompted create, `AGENTS.md` guidance. Use the full template for a dedicated planning repository; append the snippet for an existing project. Preserve existing user instructions.
7. Do not create Claude launchers, `CLAUDE.md`, `.claude/` folders, symlinks, or copied skill files. Codex discovers this plugin through its installation and marketplace configuration.

## Output

Report target path, detected VCS, stored planning root, created directories, config/ignore changes, and whether `AGENTS.md` guidance was added.
