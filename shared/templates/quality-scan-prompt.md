# Quality Review Brief

Use this brief when delegating an intent-blind quality pass to a Codex collaboration agent.

```markdown
Review the following implementation changes for correctness, safety, maintainability, tests, and unnecessary complexity.

Target repository: {{TARGET_REPO}}
Diff or file scope: {{SCOPE}}
Focus areas: {{FOCUS_LIST}}

Do not read plans, specifications, or designs. Validate every finding against the full file, callers, tests, and relevant history. Return only findings and questions using the quality-scan output format.
```
