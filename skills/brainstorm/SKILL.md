---
name: brainstorm
description: "Explore possibilities for a problem or opportunity with structured evaluation. Do NOT enter plan mode — this skill produces a brainstorm artifact directly. brainstorm, explore options, what are our options"
---

# Explore Possibilities

## Path Resolution
Read `shared/agent-runtime.md` to locate bundled resources, then read `shared/path-resolution.md` to resolve artifact and target-repository paths.

## When to Use
When you need to generate and evaluate multiple approaches to a problem before committing to one. Good for architecture decisions, feature approaches, or tool selection.

## Process

1. **Define Problem**
   - If the user hasn't already specified it, ask what problem or opportunity to explore
   - Clarify constraints and evaluation criteria

2. **Gather Context**
   - When available, delegate a bounded context scan to a collaboration subagent with the problem statement and constraints; it scans all artifact directories and the codebase per its own definition.
   - The agent returns a structured summary of relevant context

3. **Generate Ideas**
   - Build on the context gathered by the researcher
   - Brainstorm multiple approaches (aim for 3-5)
   - For each idea, document: description, pros, cons, effort level
   - Consider both conventional and creative approaches

4. **Evaluate**
   - Create `Brainstorm/<topic-slug>.md` using `shared/templates/brainstorm.md` (`<topic-slug>` is lowercase kebab-case, e.g., `auth-token-rotation`)
   - Build a comparison matrix against the criteria
   - Where architectural approaches are compared, use Mermaid diagrams to illustrate key differences
   - Make a recommendation with rationale
   - **If the user explicitly accepts the recommendation**, record it in the decision ledger per `shared/decision-log.md` — the rejected ideas go in the entry's `rejected[]`; run the collision check first (a collision stops for the user). A recommendation merely presented, not endorsed, is either left unrecorded or logged as `status: proposed` — never `accepted`.

5. **Link**
   - Add cross-references to related research or specs in `related` frontmatter

6. **Finalize**
   - Set `status: active` in the frontmatter once the document is complete and presented to the user. Then re-read the frontmatter and confirm it parses as YAML and includes `title`, `type`, `status`, `created`, `updated`, `tags`, `related`.

## Output
```
Brainstorm/<topic-slug>.md
```

## Document Structure
See `shared/templates/brainstorm.md`:
- **Problem Statement**: What we're solving
- **Ideas**: Each with description, pros, cons, effort
- **Evaluation**: Comparison matrix
- **Recommendation**: Which approach and why
- **Next Steps**: What to do with the decision

## Context
- Orchestration: `shared/orchestration.md`
- Template: `shared/templates/brainstorm.md`
- Schema: `shared/frontmatter-schema.md`
- Agent: a collaboration subagent (if available)
