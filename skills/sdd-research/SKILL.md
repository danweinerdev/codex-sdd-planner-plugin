---
name: sdd-research
description: "Investigate a topic or progressively excavate a codebase and produce a structured research document. research this, investigate, look into, excavate, explore codebase, map the code, what does this code do"
---

# Investigate a Topic

## Path Resolution
Before opening `shared/...`, follow symlinks in this loaded file's path, then derive `<plugin-root>` from `<plugin-root>/skills/<name>/SKILL.md`; fallback search roots are repository/user `.agents/` (including `$HOME/.agents/plugins/*/`), Codex `${CODEX_HOME:-$HOME/.codex}/plugins/cache/*/*/*/`, and runtime-configured skill roots. Accept only a root containing this skill, `shared/agent-runtime.md`, and the matching plugin manifest; never use the working directory. Then read `<plugin-root>/shared/agent-runtime.md` and `<plugin-root>/shared/path-resolution.md`.

**Resource boundary:** Read the plugin, all `SKILL.md` files, and `shared/` resources in place. Never copy or symlink them into the working directory, target repository, or planning root. Only generated SDD outputs may be materialized from bundled resources.

## When to Use
When you need to gather and synthesize information before making decisions.
This includes technology evaluation, external research, and progressive
codebase excavation.

## Process

1. **Define Scope**
   - If the user hasn't already specified it, ask what topic to research and what questions need answering
   - Determine if this is codebase research, external research, or both
   - For codebase research, read `planning-config.json`, resolve mapped target
     repository paths, and choose an explicit subsystem or whole-repository
     boundary

2. **Gather Information**
   - Use a collaboration subagent (if available) with the topic and questions
   - The agent will scan existing artifacts, codebase, and web as needed
   - For codebase excavation, work breadth-first then depth-first. Carry each
     pass's findings into the next:
     1. **Surface:** map directories, manifests, configuration, entry points,
        modules, and public APIs.
     2. **Structure:** establish module boundaries, dependency graph, shared
        types/models, and configuration flow.
     3. **Behavior:** trace request/data flow, state, errors, ownership, and key
        business logic.
     4. **Patterns:** identify conventions, tests, build/deploy paths, TODOs,
        FIXMEs, deprecated code, and other named technical debt.
   - Follow the data rather than reading files top-to-bottom. Record surprises
     and claims that could not be verified. Stop at diminishing returns, when
     every major component and interaction in scope can be explained with cited
     evidence.

3. **Synthesize**
   - Create `Research/<topic-slug>.md` using `shared/templates/research.md` (`<topic-slug>` is lowercase kebab-case, e.g., `auth-token-rotation`)
   - Organize findings into Context, Key Insights, Sources, Analysis
   - For codebase excavation, additionally include Architecture, Key Patterns,
     Data Flow, Dependencies, and Risks; use Mermaid inline where structure
     materially improves the explanation
   - Highlight implications and recommendations
   - Call out discoveries that warrant a new or revised specification
   - List open questions that remain

4. **Link**
   - Add cross-references to related artifacts in the `related` frontmatter field

5. **Finalize**
   - Set `status: active` in the frontmatter once the document is complete and presented to the user. Then re-read the frontmatter and confirm it parses as YAML and includes `title`, `type`, `status`, `created`, `updated`, `tags`, `related`.

## Output
```
Research/<topic-slug>.md
```

## Document Structure
See `shared/templates/research.md`:
- **Context**: Why this research is needed
- **Findings**: Key insights and sources
- **Analysis**: Implications and recommendations
- **Open Questions**: What remains unknown

Codebase excavation additionally uses:
- **Architecture**: Components, boundaries, and interactions
- **Key Patterns**: Conventions and recurring implementation choices
- **Data Flow**: Request, state, and ownership movement
- **Dependencies**: Internal and external dependency graph
- **Risks**: Surprises, technical debt, and unverified assumptions

## Context
- Orchestration: `shared/orchestration.md`
- Template: `shared/templates/research.md`
- Schema: `shared/frontmatter-schema.md`
- Agent: a collaboration subagent (if available)
