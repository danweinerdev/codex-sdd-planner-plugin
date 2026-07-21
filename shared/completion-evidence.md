# Completion Evidence

Prospective `verification` says how work will be judged. Retrospective
completion evidence records what actually ran and what it proved. A task,
phase, or plan may not transition to `complete` until its required evidence
section is populated and passes the rules below (D-0005).

## Required sections

- Every task body has `### Completion Evidence` within its `## <task-id>`
  section.
- Every phase document has `## Phase Completion Evidence`.
- Every plan README has `## Plan Completion Evidence`.

Incomplete work starts with the literal line `Pending — not complete.` in its
evidence section. The evidence may be populated while status is still
non-complete so it can be validated before the status transition. A `complete`
status and a pending or absent evidence section are contradictory states.

## Task evidence

Before setting a task to `complete`, replace the pending marker with:

```markdown
### Completion Evidence

- Verified: YYYY-MM-DD
- Repository: `<repository root>`
- VCS: `git | git-worktree | perforce | none`
- Revision / base: `<exact clean Git revision>`, `<Git base>-dirty`, `<Perforce have digest>`, or `none`
- Evidence exclusions: `<exact repository-relative SDD artifact paths, or none>`
- Governing intent: `<sha256 digest> at <durable projection path>; inputs: <paths and decision ids>`
- Ignored inputs: `<captured paths and digests, or none with inspection basis>`
- Directory inputs: `<captured empty/relevant directories and modes, or none with inspection basis>`
- Content snapshot: `<sha256 digest> at <durable canonical manifest path>` (required for dirty Git, Perforce, or no VCS)
- Identity recheck: `<exact command/tool, timestamp, and matching revision/digest>`

| Command | Working directory | Result | Observable evidence |
|---|---|---|---|
| `<exact command>` | `<path>` | PASS (`exit 0`) | `<specific output or behavior observed>` |

| Tool / inspection | Context | Result | Observable evidence |
|---|---|---|---|
| `<tool and version, or exact non-command procedure>` | `<paths/environment>` | PASS | `<specific observation>` |
```

Rules:

1. Record the exact command, not “tests passed” or a paraphrased tool name.
2. Record the working directory and exit status for every command.
3. Record the observable result that satisfies the task's prospective
   `verification`; test counts alone are insufficient when named behaviors were
   required.
4. Record the tested source identity using the canonical procedure below. A
   changed-path list, ordinary text patch, or revision without the identity
   recheck is not reproducible evidence.
5. Name non-command tools and procedures precisely, including version when it
   affects reproducibility, plus the inspected paths/environment and observed
   result.
6. Remove an unused table only when that evidence class does not apply. At
   least one command or tool/inspection row is required. When behavior cannot
   be command-verified, state why and provide the exact non-command evidence.
7. A final required check that failed means the task is not complete. Preserve
   failure output verbatim in the session report or linked durable artifact;
   never rewrite failure as passing evidence.

## Canonical source identity

Source identity covers every target repository touched by the task. Record a
separate revision/snapshot for each repository. The repository root, detected
VCS kind, full base identity, and governing-intent digest are part of the
identity. A Git bare repository is unsupported: operate in a worktree. Do not
improvise an identity for an unrecognized VCS.

The only permitted content-snapshot exclusions are exact repository-relative
paths of the governing phase document, plan README, phase debrief, canonical
snapshot manifest/content objects, and governing-intent projection object when
those files exist solely to record SDD evidence or lifecycle status. Evidence
capture paths must live under the planning root. The phase document and plan
README remain covered by the governing-intent digest below; excluding them does
not permit intent changes.
List every exclusion in the evidence. Source, tests, fixtures, generated
source, configuration, and any other implementation content may not be
excluded.

Compute `Governing intent` over an explicit input set: the plan README,
governing phase document, every governing spec/design consulted or cited by the
task, and every accepted decision consulted or cited by id. Resolve all
citations and record the sorted input references in evidence; an unresolved or
omitted governing input is nonconforming.

All projected artifacts must be UTF-8 with LF endings. Lifecycle fields must
use block-style YAML with each removable scalar on its own complete line and no
other node or comment on that line; flow-style or multiline lifecycle fields
are nonconforming until normalized. For plans/phases, remove only lines whose
parsed YAML path is top-level `updated`, top-level `status`,
`phases[*].status`, or `tasks[*].status`; replace each completion-evidence
section body with the exact line `Pending — not complete.\n`; and normalize
`[x]`/`[X]` to `[ ]` only in Subtasks and Acceptance Criteria. For governing
specs/designs, remove only standalone top-level `updated` and `status` lines.
For a decision input, project the exact YAML bytes of that one entry from its
`- id:` line through the byte before the next entry at the same indentation.
Retain every other byte.

The durable projection object is `sdd-intent-v2\n` followed, in encoded input-
reference order, by
`input\t<artifact-or-decision>\t<encoded-reference>\t<byte-count>\n<projected-bytes>`
for every input. `byte-count` is decimal and makes adjacent records
unambiguous. Paths/references use the encoding below. Store the exact projection
bytes at the recorded durable path and record their SHA-256. Recompute the
current projection during every pre-completion or pre-closure identity recheck;
a changed input set or digest invalidates prior verification. For an already-
closed historical entity, validate the durable projection bytes and digest but
do not compare them to artifacts legitimately revised by later work; report
later governing revisions separately as drift when applicable.

For a clean Git identity, the index and worktree content must match the recorded
full revision after applying only those exclusions, every non-excluded staged
path must match its worktree bytes/mode, and there must be no non-ignored
untracked file outside the exclusions.
Evidence edits may make the repository globally dirty; “clean” means
implementation content is clean under this rule, not that a bare VCS status
command prints nothing.

For a dirty identity, store a canonical snapshot manifest and content objects:

1. For Git, compare final worktree content to the fixed full base revision and
   enumerate every non-ignored untracked file. Require every staged path to
   match its worktree bytes/mode so hidden index content cannot later be
   committed untested. Treat a path absent from the base as `A` regardless of
   whether it is currently tracked. Include all differences except the
   permitted exclusions; do not select only paths believed relevant. Keep the
   recorded base fixed across evidence-only or implementation commits so the
   same tested bytes retain the same identity.
2. The manifest is UTF-8/ASCII with LF endings and a final LF. Its first two
   lines are `sdd-dirty-snapshot-v1` and `base\t<full-revision>`. Then emit one
   `exclude\t<path>` line per exclusion, one
   `directory\t<mode>\t<path>` line per captured directory, and one
   `entry\t<state>\t<mode>\t<size>\t<sha256>\t<path>` line per changed object.
   Emit those groups in that order and sort each by encoded path. Capture every
   empty directory and every directory whose existence or permissions affect
   verification or delivery; list them under `Directory inputs`. States are
   `A`, `M`, `D`, and `T`. Modes are lowercase fixed-width six-digit octal POSIX
   `st_mode & 0177777`, including type bits; use the final mode, byte size, and
   SHA-256 of raw content. Deletion uses mode `000000`, size `0`, and digest
   `-`. Reject identity capture on a platform that cannot report equivalent
   POSIX mode semantics.
3. Encode path bytes using ASCII letters, digits, `.`, `_`, `-`, and `/`
   literally and every other byte as uppercase `%HH`. Capture regular-file
   bytes exactly and symlink target bytes as content. A dirty submodule or
   nested repository requires its own snapshot and an evidence row naming its
   digest; the parent gitlink alone is insufficient.
4. Store every non-deletion content object at
   `<manifest-path>.contents/<sha256>` with exactly the hashed bytes. SHA-256 of
   the exact manifest bytes is the recorded content-snapshot digest.
5. A durable path is either a VCS-tracked artifact committed with the SDD
   evidence or an immutable, content-addressed artifact URI with recorded
   retention. Because the base stays fixed and evidence paths are explicit
   exclusions, committing only implementation/evidence files does not alter
   the tested content identity; changing any implementation byte does. A
   mutable temporary file is not durable.

Git ignore rules do not prove irrelevance. Include every ignored file read,
executed, or produced by verification, used as configuration/input, or shipped
as part of the deliverable as an `A`/`M` manifest entry and content object.
Include every ignored directory with relevant existence/mode as a directory
entry. Record each included ignored path under `Ignored inputs` and every
captured directory under `Directory inputs`. For omitted ignored paths or
directories, record the exact inspection/tool basis establishing that they
cannot affect verification or the deliverable; an unsupported blanket
“ignored” claim is nonconforming.

For Perforce and no-VCS workspaces, use this complete
`sdd-content-snapshot-v1` grammar instead of the Git delta manifest:

1. Snapshot every directory, regular file, and symlink recursively under the
   target root except permitted exclusions. Include empty directories and
   directory modes. Reject unsupported special files.
2. Emit these LF-terminated sections in order: `sdd-content-snapshot-v1`;
   `vcs\tperforce` or `vcs\tnone`; one `base\t<value>` line; sorted
   `exclude\t<encoded-path>` lines; sorted Perforce `have` lines when
   applicable; then sorted `entry` lines. The file ends with LF.
3. For Perforce, each have line is
   `have\t<encoded-depot-path>#<revision>\t<encoded-local-path>`. `base` is
   SHA-256 of the exact concatenated have-line bytes. Include the complete
   client mapping, including mapped files locally deleted. For no VCS, use
   `base\tnone` and no have lines.
4. Each entry is
   `entry\t<state>\t<type>\t<mode>\t<size>\t<sha256>\t<encoded-path>`.
   State is `P` for present or `D` for a locally deleted Perforce mapping. Type
   is `d`, `f`, or `l` for directory, regular file, or symlink. Mode is lowercase
   fixed-width six-digit octal POSIX `st_mode & 0177777`, including type bits;
   reject capture when equivalent POSIX mode semantics are unavailable. Present
   directories use size `0` and digest `-`; deleted entries use type `-`, mode
   `000000`, size `0`, and digest `-`; files hash raw bytes; symlinks hash raw
   target bytes. Entry sorting is by encoded path, then state and type.
5. Store every present file/symlink object at
   `<manifest-path>.contents/<sha256>`. For Perforce, include mapped, opened,
   reconciled, and local content. SHA-256 of the exact full manifest bytes is
   the recorded source identity.

This full snapshot is required even when Perforce has no pending edits or the
workspace has no VCS. Files or directories outside the target root that affect
verification must be listed as environment/input artifacts with exact paths,
content digests, and durable captures.

Capture this identity immediately after the recorded verification commands.
After writing evidence, recompute it with the same base and exclusions
immediately before each task/phase/plan status transition. Record the exact
recheck command or tool, timestamp, and matching revision/digest. Before a
Beads closure, recompute it again. Any non-excluded difference from the tested
identity makes the evidence stale and forbids completion or closure.

## Phase evidence

Before setting a phase to `complete`, replace `Pending — not complete.` under
`## Phase Completion Evidence` with:

- verification date and canonical source identity under the task-evidence
  rules, including durable snapshot capture when required;
- the VCS kind, exact exclusions, governing-intent digest, ignored/directory-
  input inventories, and successful identity recheck;
- a rollup of every task id that repeats its populated `### Completion
  Evidence` section verbatim;
- exact phase-level commands/tools and results when the phase acceptance
  criteria require integration or aggregate checks; and
- either those aggregate checks or an explicit statement that no additional
  phase-level check applies, with the reason task evidence fully covers every
  phase acceptance criterion.

All phase acceptance-criteria checkboxes and tasks must be complete first. Every
required phase-level check must pass; a failed or unrun aggregate check forbids
phase completion.

## Plan evidence

Before setting a plan to `complete`, replace `Pending — not complete.` under
`## Plan Completion Evidence` with:

- verification date and canonical source identity under the task-evidence
  rules, including durable snapshot capture when required;
- the VCS kind, exact exclusions, governing-intent digest, ignored/directory-
  input inventories, and successful identity recheck;
- a rollup for every phase and task that repeats the exact commands/tools,
  context, results, and observable evidence from their completion sections;
  links may supplement the rollup but references alone are insufficient;
- exact plan-level end-to-end/release commands or tools and results when the
  plan's deliverable requires them; and
- either those final checks or an explicit statement that no additional
  plan-level check applies, with the reason phase evidence fully proves the
  plan deliverable.

Every phase must be complete first. Every required plan-level check must pass;
a failed or unrun final check forbids plan completion.

## Legacy completed artifacts

Artifacts already marked `complete` without the required section are legacy
evidence gaps. Do not fabricate evidence, silently downgrade status, or infer
commands from checked boxes. `sdd-validate` reports them. They become conforming
only when verification is rerun or a contemporaneous durable record (for
example, CI output tied to a revision) supplies every required field.
