from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "sdd_validate.py"
SPEC = importlib.util.spec_from_file_location("sdd_validate", SCRIPT)
assert SPEC and SPEC.loader
sdd_validate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sdd_validate
SPEC.loader.exec_module(sdd_validate)


def write(root: Path, relative: str, contents: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def spec_document() -> str:
    return """
        ---
        title: Feature
        type: spec
        status: approved
        created: 2026-07-21
        updated: 2026-07-21
        tags: [feature]
        related: []
        ---
        # Feature
        ## Overview
        Feature overview.
        ## Goals
        - Goal.
        ## Non-Goals
        - Non-goal.
        ## Requirements
        ### Functional Requirements
        - **FR-01**: Do the thing.
        ### Non-Functional Requirements
        - **NFR-01**: Remain deterministic.
        ## User Stories
        - As a user, I can do the thing.
        ## Acceptance Criteria
        - [ ] **AC-01**: The thing works.
        ## Constraints
        - Constraint.
        ## Dependencies
        - None.
        ## Open Questions
        - None.
    """


def plan_document(phase_status: str = "planned", depends_on: str = "") -> str:
    dependency = f"    depends_on: [{depends_on}]\n" if depends_on else ""
    return f"""
        ---
        title: Feature Plan
        type: plan
        status: active
        created: 2026-07-21
        updated: 2026-07-21
        tags: [feature]
        related: [Specs/Feature]
        phases:
          - id: 1
            title: Build
            status: {phase_status}
            doc: 01-Build.md
        {dependency.rstrip()}
        ---
        # Feature Plan
        ## Overview
        Build the feature.
        ## Architecture
        One component.
        ## Key Decisions
        None.
        ## Dependencies
        None.
        ## Plan Completion Evidence
        Pending — not complete.
    """


def phase_document(task_status: str = "planned", depends_on: str = "") -> str:
    dependency = f'    depends_on: ["{depends_on}"]\n' if depends_on else ""
    return f"""
        ---
        title: Build
        type: phase
        plan: Feature
        phase: 1
        status: planned
        created: 2026-07-21
        updated: 2026-07-21
        deliverable: Feature implementation
        tasks:
          - id: "1.1"
            title: Implement
            status: {task_status}
            verification: "Run tests and satisfy FR-01, NFR-01, and AC-01"
        {dependency.rstrip()}
        ---
        # Phase 1: Build
        ## Overview
        Build it according to FR-01 and NFR-01.
        ## 1.1: Implement
        ### Subtasks
        - [ ] Implement it.
        ### Notes
        Follow AC-01.
        ### Completion Evidence
        Pending — not complete.
        ## Acceptance Criteria
        - [ ] AC-01
        ## Phase Completion Evidence
        Pending — not complete.
    """


class ValidatorTests(unittest.TestCase):
    def make_valid_tree(self, root: Path) -> None:
        write(root, "Specs/Feature/README.md", spec_document())
        write(root, "Plans/Feature/README.md", plan_document())
        write(root, "Plans/Feature/01-Build.md", phase_document())
        write(
            root,
            "Decisions/decisions.md",
            """
            ---
            title: Decision Ledger
            type: decision-log
            status: active
            created: 2026-07-21
            updated: 2026-07-21
            tags: [decisions]
            related: []
            decisions: []
            ---
            # Decision Ledger
            """,
        )

    def validate(self, root: Path) -> list[object]:
        return sdd_validate.Validator(root, root).run()

    def test_valid_artifact_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.assertEqual([], self.validate(root))

    def test_reports_status_drift_unknown_dependency_and_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(root, "Plans/Feature/README.md", plan_document(phase_status="blocked", depends_on="1"))
            write(root, "Plans/Feature/01-Build.md", phase_document(depends_on="1.1"))
            codes = {item.code for item in self.validate(root)}
            self.assertTrue({"SDD058", "SDD131", "SDD132", "SDD134", "SDD135"}.issubset(codes))

    def test_reports_review_and_decision_integrity_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(
                root,
                "Plans/Feature/reviews/01-feature-code-review-test.md",
                """
                ---
                title: Review
                type: review
                status: resolved
                created: 2026-07-21
                updated: 2026-07-21
                tags: [review]
                related: [Plans/Feature]
                review_of: Plans/Feature
                rev: test
                findings:
                  - id: F-01
                    severity: major
                    title: Deferred issue
                    status: open
                followups:
                  - id: FU-01
                    finding: F-01
                    summary: Follow up
                    tracked_in: ""
                ---
                # Review
                ## Findings
                ### F-01 — Major Deferred issue
                Scenario.
                ## Resolution Log
                None.
                """,
            )
            codes = {item.code for item in self.validate(root)}
            self.assertIn("SDD091", codes)
            self.assertIn("SDD095", codes)

    def test_cli_emits_machine_readable_json_and_nonzero_for_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(root, "Plans/Feature/README.md", plan_document(phase_status="blocked"))
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(1, completed.returncode)
            self.assertFalse(payload["valid"])
            self.assertTrue(payload["diagnostics"])

    def test_explicit_planning_root_preserves_invocation_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            root = repo / ".plans"
            (repo / ".git").mkdir(parents=True)
            root.mkdir()
            resolved_root, resolved_repo = sdd_validate.resolve_roots(PLUGIN_ROOT, str(root))
            self.assertEqual(root.resolve(), resolved_root)
            self.assertEqual(PLUGIN_ROOT.resolve(), resolved_repo)

    def test_task_ids_are_scoped_to_their_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(
                root,
                "Plans/Other/README.md",
                plan_document().replace("Feature Plan", "Other Plan").replace(
                    "Plans/Feature", "Plans/Other"
                ),
            )
            write(
                root,
                "Plans/Other/01-Build.md",
                phase_document().replace("plan: Feature", "plan: Other"),
            )
            codes = [item.code for item in self.validate(root)]
            self.assertNotIn("SDD031", codes)

    def test_cli_rejects_empty_root_and_unknown_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, empty.returncode)
            self.make_valid_tree(root)
            unknown = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--scope", "Typo", "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, unknown.returncode)
            self.assertIn("does not resolve", json.loads(unknown.stdout)["error"])

    def test_code_spanned_dirty_evidence_requires_and_validates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            evidence = root / "evidence"
            evidence.mkdir()
            projection_validator = sdd_validate.Validator(root, root)
            projection_validator._discover()
            input_references = (
                "Plans/Feature/01-Build.md",
                "Plans/Feature/README.md",
                "Specs/Feature/README.md",
            )
            intent = b"sdd-intent-v2\n"
            for reference in input_references:
                projected = sdd_validate.project_artifact(
                    projection_validator.by_path[reference]
                )
                intent += (
                    f"input\tartifact\t{reference}\t{len(projected)}\n".encode()
                    + projected
                )
            intent_path = evidence / "intent.bin"
            intent_path.write_bytes(intent)
            content = b"abc"
            object_digest = hashlib.sha256(content).hexdigest()
            snapshot_path = evidence / "snapshot.manifest"
            object_dir = Path(f"{snapshot_path}.contents")
            object_dir.mkdir()
            (object_dir / object_digest).write_bytes(content)
            snapshot = (
                "sdd-dirty-snapshot-v1\n"
                f"base\t{'a' * 40}\n"
                f"entry\tM\t100644\t3\t{object_digest}\tfile.txt\n"
            ).encode()
            snapshot_path.write_bytes(snapshot)
            block = f"""
            - Verified: 2026-07-21
            - Repository: `{root}`
            - VCS: `git`
            - Revision / base: `{'a' * 40}-dirty`
            - Evidence exclusions: `none`
            - Governing intent: `{hashlib.sha256(intent).hexdigest()}` at `evidence/intent.bin`; inputs: {", ".join(input_references)}
            - Ignored inputs: `none with inspection basis`
            - Directory inputs: `none with inspection basis`
            - Content snapshot: `{hashlib.sha256(snapshot).hexdigest()}` at `evidence/snapshot.manifest`
            - Identity recheck: `validator`, 2026-07-21T12:00:00Z, matched snapshot

            | Command | Working directory | Result | Observable evidence |
            |---|---|---|---|
            | `python3 -m unittest` | `{root}` | PASS (`exit 0`) | Named behavior passed. |
            """
            phase = phase_document(task_status="complete")
            phase = phase.replace("status: planned", "status: complete", 1)
            phase = phase.replace("- [ ] Implement it.", "- [x] Implement it.")
            phase = phase.replace("- [ ] AC-01", "- [x] AC-01")
            phase = phase.replace("Pending — not complete.", textwrap.dedent(block).strip())
            write(root, "Plans/Feature/01-Build.md", phase)
            write(root, "Plans/Feature/README.md", plan_document(phase_status="complete"))
            codes = {item.code for item in self.validate(root)}
            self.assertFalse({"SDD070", "SDD071", "SDD072", "SDD074", "SDD075", "SDD076", "SDD077", "SDD078", "SDD079"} & codes)

    def test_snapshot_validator_detects_tampered_content_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.manifest"
            digest = hashlib.sha256(b"expected").hexdigest()
            object_dir = Path(f"{path}.contents")
            object_dir.mkdir()
            (object_dir / digest).write_bytes(b"tampered")
            manifest = (
                "sdd-dirty-snapshot-v1\n"
                f"base\t{'b' * 40}\n"
                f"entry\tM\t100644\t8\t{digest}\tfile.txt\n"
            ).encode()
            errors = sdd_validate.validate_snapshot(path, manifest)
            self.assertTrue(any("size" in error or "digest" in error for error in errors))

    def test_external_plan_mapping_loads_target_repository_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            coordinator = base / "coordinator"
            root = base / "planning"
            target = base / "target"
            (coordinator / ".git").mkdir(parents=True)
            target.mkdir()
            self.make_valid_tree(root)
            plan_path = root / "Plans/Feature/README.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8").replace(
                    "## Key Decisions\nNone.", "## Key Decisions\nUse the target repository ledger (D-0001)."
                ),
                encoding="utf-8",
            )
            (coordinator / "planning-config.json").write_text(
                json.dumps(
                    {
                        "planningRoot": str(root),
                        "repositories": {"target": {"path": str(target)}},
                        "planMapping": {"Feature": "target"},
                    }
                ),
                encoding="utf-8",
            )
            write(
                target,
                "DECISIONS.md",
                """
                ---
                title: Target Decisions
                type: decision-log
                status: active
                created: 2026-07-21
                updated: 2026-07-21
                tags: [decisions]
                related: []
                decisions:
                  - id: D-0001
                    kind: decision
                    status: accepted
                    date: 2026-07-21
                    decided_by: user
                    statement: Use the target repository.
                    rationale: It owns implementation.
                    scope: [Plans/Feature]
                    tags: [target]
                    rejected: []
                ---
                # Target Decisions
                """,
            )
            diagnostics = sdd_validate.Validator(root, coordinator).run()
            codes = {item.code for item in diagnostics}
            self.assertNotIn("SDD120", codes)
            self.assertNotIn("SDD145", codes)
            self.assertNotIn("SDD146", codes)

    def test_related_scopes_expose_conflicting_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            spec_path = root / "Specs/Feature/README.md"
            spec_path.write_text(
                spec_path.read_text(encoding="utf-8").replace(
                    "Feature overview.", "Feature overview governed by D-0001."
                ),
                encoding="utf-8",
            )
            write(
                root,
                "Designs/Feature/README.md",
                """
                ---
                title: Feature Design
                type: design
                status: approved
                created: 2026-07-21
                updated: 2026-07-21
                tags: [feature]
                related: [Specs/Feature]
                ---
                # Feature Design
                ## Overview
                Governed by D-0002.
                ## Architecture
                Architecture.
                ## Design Decisions
                Decisions.
                ## Error Handling
                Errors.
                ## Testing Strategy
                Tests.
                ## Migration / Rollout
                Rollout.
                """,
            )
            write(
                root,
                "Decisions/decisions.md",
                """
                ---
                title: Decision Ledger
                type: decision-log
                status: active
                created: 2026-07-21
                updated: 2026-07-21
                tags: [decisions]
                related: []
                decisions:
                  - id: D-0001
                    kind: definition
                    status: accepted
                    date: 2026-07-21
                    decided_by: user
                    statement: Widget means the first behavior.
                    rationale: First definition.
                    scope: [Specs/Feature]
                    tags: [widget]
                    rejected: []
                  - id: D-0002
                    kind: definition
                    status: accepted
                    date: 2026-07-21
                    decided_by: user
                    statement: Widget means the second behavior.
                    rationale: Second definition.
                    scope: [Designs/Feature]
                    tags: [widget]
                    rejected: []
                ---
                # Decision Ledger
                """,
            )
            codes = {item.code for item in self.validate(root)}
            self.assertIn("SDD149", codes)

    def test_absolute_and_parent_related_paths_do_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            plan = plan_document().replace(
                "related: [Specs/Feature]",
                "related: [/Specs/Feature, ../Specs/Feature]",
            )
            write(root, "Plans/Feature/README.md", plan)
            related_errors = [
                item for item in self.validate(root) if item.code == "SDD041"
            ]
            self.assertEqual(2, len(related_errors))

    def test_snapshot_must_match_recorded_base_and_exclusions(self) -> None:
        manifest = (
            "sdd-dirty-snapshot-v1\n"
            f"base\t{'a' * 40}\n"
            "exclude\tPlans/Feature/README.md\n"
            f"entry\tD\t000000\t0\t-\tdeleted.txt\n"
        ).encode()
        errors = sdd_validate.validate_snapshot(
            Path("snapshot"),
            manifest,
            "git",
            f"{'b' * 40}-dirty",
            set(),
        )
        self.assertTrue(any("base" in error for error in errors))

    def test_evidence_rows_preserve_kind_and_nonpassing_results(self) -> None:
        rows = sdd_validate.evidence_rows(
            """
            | Command | Working directory | Result | Observable evidence |
            |---|---|---|---|
            | `pytest` | `/repo` | SKIPPED | Not executed. |

            | Tool / inspection | Context | Result | Observable evidence |
            |---|---|---|---|
            | `reviewer` | `file` | PASS | Inspected. |
            """
        )
        self.assertEqual("command", rows[0][0])
        self.assertEqual("SKIPPED", rows[0][1][2])
        self.assertEqual("tool", rows[1][0])

    def test_plan_review_inherits_specs_and_tracks_followup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(
                root,
                "Specs/Feature/reviews/01-feature-code-review-test.md",
                """
                ---
                title: Feature Review
                type: review
                status: resolved
                created: 2026-07-21
                updated: 2026-07-21
                tags: [review]
                related: [Specs/Feature, Plans/Feature]
                review_of: Specs/Feature
                rev: test
                findings:
                  - id: F-01
                    severity: major
                    title: Follow-up required
                    status: deferred
                followups:
                  - id: FU-01
                    finding: F-01
                    summary: Implement the requirement
                    tracked_in: "1.1"
                ---
                # Feature Review
                ## Findings
                ### F-01 — Major Follow-up required
                **Impugns:** FR-01 and AC-01.
                ## Resolution Log
                ### F-01 — deferred (2026-07-21)
                Tracked in task 1.1.
                """,
            )
            findings = self.validate(root)
            codes = {item.code for item in findings}
            self.assertNotIn("SDD096", codes)
            self.assertNotIn("SDD098", codes)
            self.assertNotIn("SDD122", codes)

    def test_review_supersession_requires_lifecycle_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            old_path = "Plans/Feature/reviews/01-feature-code-review-old.md"
            new_path = "Plans/Feature/reviews/02-feature-code-review-new.md"
            write(
                root,
                old_path,
                f"""
                ---
                title: Old Review
                type: review
                status: open
                created: 2026-07-21
                updated: 2026-07-21
                tags: [review]
                related: [Plans/Feature]
                review_of: Plans/Feature
                rev: old
                findings: []
                followups: []
                superseded_by: {new_path}
                ---
                # Old Review
                ## Findings
                None.
                ## Resolution Log
                None.
                """,
            )
            write(
                root,
                new_path,
                f"""
                ---
                title: New Review
                type: review
                status: open
                created: 2026-07-21
                updated: 2026-07-21
                tags: [review]
                related: [Plans/Feature]
                review_of: Plans/Feature
                rev: new
                findings: []
                followups: []
                supersedes: {old_path}
                ---
                # New Review
                ## Findings
                None.
                ## Resolution Log
                None.
                """,
            )
            codes = {item.code for item in self.validate(root)}
            self.assertIn("SDD099", codes)
            self.assertIn("SDD102", codes)

    def test_no_vcs_nested_start_finds_parent_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            nested = repo / "a" / "b"
            nested.mkdir(parents=True)
            (repo / ".plans").mkdir()
            (repo / "planning-config.json").write_text(
                json.dumps({"planningRoot": ".plans"}), encoding="utf-8"
            )
            root, resolved_repo = sdd_validate.resolve_roots(nested, None)
            self.assertEqual((repo / ".plans").resolve(), root)
            self.assertEqual(repo.resolve(), resolved_repo)

    def test_active_plan_requires_requirement_and_acceptance_citations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            phase = phase_document().replace("NFR-01", "unlinked-NFR").replace(
                "AC-01", "unlinked-AC"
            )
            write(root, "Plans/Feature/01-Build.md", phase)
            codes = {item.code for item in self.validate(root)}
            self.assertIn("SDD160", codes)
            self.assertIn("SDD162", codes)
            validator = sdd_validate.Validator(root, root)
            scoped = sdd_validate.select(validator.run(), "Specs/Feature")
            self.assertTrue(any(item.code in {"SDD160", "SDD162"} for item in scoped))

    def test_clean_git_identity_checks_commit_and_current_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "fixture",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            validator = sdd_validate.Validator(root, root, "current")
            validator._discover()
            plan = validator.by_path["Plans/Feature/README.md"]
            validator._verify_clean_git_identity(
                plan, revision, set(), "Plan Completion Evidence", 1, True
            )
            self.assertEqual([], validator.out)
            (root / "changed.txt").write_text("changed", encoding="utf-8")
            validator._verify_clean_git_identity(
                plan, revision, set(), "Plan Completion Evidence", 1, True
            )
            self.assertTrue(any("current worktree differs" in item.message for item in validator.out))

    def test_intent_projection_rejects_noncanonical_artifact_payload(self) -> None:
        payload = b"---\ntype: plan\n---\n"
        content = (
            b"sdd-intent-v2\ninput\tartifact\tPlans/Feature/README.md\t"
            + str(len(payload)).encode()
            + b"\n"
            + payload
        )
        error, _, _ = sdd_validate.validate_intent_projection(content)
        self.assertIn("missing common fields", error or "")

    def test_ipfs_cid_multihash_must_equal_recorded_sha256(self) -> None:
        digest = hashlib.sha256(b"durable evidence").digest()
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        number = int.from_bytes(b"\x12\x20" + digest, "big")
        encoded = ""
        while number:
            number, remainder = divmod(number, 58)
            encoded = alphabet[remainder] + encoded
        cid = encoded
        self.assertEqual(digest.hex(), sdd_validate.ipfs_sha256(f"ipfs://{cid}"))
        self.assertNotEqual("00" * 32, sdd_validate.ipfs_sha256(f"ipfs://{cid}"))

    def test_required_intent_inputs_are_derived_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            validator = sdd_validate.Validator(root, root)
            validator._discover()
            validator._index()
            phase = validator.by_path["Plans/Feature/01-Build.md"]
            self.assertEqual(
                {
                    "Plans/Feature/01-Build.md",
                    "Plans/Feature/README.md",
                    "Specs/Feature/README.md",
                },
                validator._required_intent_inputs(phase),
            )


if __name__ == "__main__":
    unittest.main()
