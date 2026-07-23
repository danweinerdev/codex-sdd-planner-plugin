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

    def commit_all(self, root: Path) -> str:
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
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_valid_artifact_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.assertEqual([], self.validate(root))

    def test_core_templates_state_the_validator_format_contract(self) -> None:
        templates = {
            kind: (PLUGIN_ROOT / "shared" / "templates" / filename).read_text(
                encoding="utf-8"
            )
            for kind, filename in {
                "spec": "spec.md",
                "design": "design.md",
                "plan": "plan-readme.md",
                "phase": "plan-phase.md",
            }.items()
        }

        for kind, headings in sdd_validate.REQUIRED_HEADINGS.items():
            if kind not in templates:
                continue
            for heading in headings:
                self.assertIn(f"## {heading}", templates[kind])
            for status in sdd_validate.STATUS[kind]:
                self.assertIn(f"`{status}`", templates[kind])
            for field in sdd_validate.COMMON_FIELDS:
                self.assertIn(f"{field}:", templates[kind])
            self.assertIn("sdd-validate format contract", templates[kind])
            self.assertNotIn("\r\n", templates[kind])

        for family, pattern in sdd_validate.DEFINITIONS.items():
            self.assertIsNotNone(pattern.search(templates["spec"]), family)
        self.assertIn("exact parser", templates["spec"])
        self.assertIn("collectively must cite every FR-NN and NFR-NN", templates["design"])

        plan = templates["plan"]
        self.assertIn("#   - id:", plan)
        for field in ("title", "status", "doc"):
            self.assertIn(f"#     {field}:", plan)
        self.assertRegex(plan, r"no unknown IDs,\s+self-dependencies, or cycles")

        phase = templates["phase"]
        for field in ("id", "title", "status", "verification"):
            self.assertIn(f"#   {field}:", phase)
        self.assertIn("`<phase>.<digits>`", phase)
        self.assertIn("exact H3 headings `Subtasks`,\n  `Notes`, and `Completion Evidence`", phase)

        for evidence_template in (plan, phase):
            for label in (
                "Verified",
                "Repository",
                "VCS",
                "Revision / base",
                "Evidence exclusions",
                "Governing intent",
                "Ignored inputs",
                "Directory inputs",
                "Identity recheck",
                "Fallback reason",
            ):
                self.assertIn(f"`{label}`", evidence_template)
            self.assertIn(
                "`Command | Working directory | Result | Observable evidence`",
                evidence_template,
            )
            self.assertIn(
                "`Tool / inspection | Context | Result | Observable evidence`",
                evidence_template,
            )
            self.assertIn("`PASS (exit 0)`", evidence_template)

    def test_plan_phase_docs_require_type_backlink_and_matching_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            phase = phase_document()
            phase = phase.replace("type: phase", "type: design", 1)
            phase = phase.replace("plan: Feature", "plan: Other", 1)
            phase = phase.replace("title: Build", "title: Other", 1)
            write(root, "Plans/Feature/01-Build.md", phase)
            codes = {item.code for item in self.validate(root)}
            self.assertTrue({"SDD150", "SDD151", "SDD152"}.issubset(codes))

    def test_every_phase_is_owned_once_by_its_physical_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            rogue = phase_document().replace("phase: 1", "phase: 9", 1)
            rogue = rogue.replace('id: "1.1"', 'id: "9.1"', 1)
            rogue = rogue.replace("## 1.1:", "## 9.1:", 1)
            write(root, "Plans/Other/09-Rogue.md", rogue)
            findings = [item for item in self.validate(root) if item.code == "SDD163"]
            self.assertEqual(1, len(findings))
            self.assertEqual("Plans/Other/09-Rogue.md", findings[0].path)

    def test_git_head_ids_are_append_only_but_retirement_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.commit_all(root)

            spec = spec_document().replace("FR-01", "FR-02")
            write(root, "Specs/Feature/README.md", spec)
            plan = plan_document().replace("- id: 1", "- id: 2", 1)
            write(root, "Plans/Feature/README.md", plan)
            phase = phase_document().replace('id: "1.1"', 'id: "1.2"', 1)
            write(root, "Plans/Feature/01-Build.md", phase)
            codes = {item.code for item in self.validate(root)}
            self.assertTrue({"SDD154", "SDD155", "SDD156"}.issubset(codes))

            retired = spec_document().replace(
                "- **FR-01**: Do the thing.",
                "- **FR-01**: removed — see requirements retirement record",
            )
            write(root, "Specs/Feature/README.md", retired)
            self.assertNotIn(
                "SDD154",
                {item.code for item in self.validate(root) if item.path == "Specs/Feature/README.md"},
            )

    def test_append_only_ids_cover_deleted_paths_and_hidden_index_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.commit_all(root)
            spec_path = root / "Specs" / "Feature" / "README.md"

            staged = spec_document().replace("FR-01", "FR-02")
            spec_path.write_text(textwrap.dedent(staged).lstrip(), encoding="utf-8")
            subprocess.run(["git", "add", str(spec_path)], cwd=root, check=True)
            spec_path.write_text(textwrap.dedent(spec_document()).lstrip(), encoding="utf-8")
            findings = [item for item in self.validate(root) if item.code == "SDD154"]
            self.assertTrue(any("index" in item.message for item in findings))

            substituted = spec_document().replace("type: spec", "type: design", 1)
            spec_path.write_text(textwrap.dedent(substituted).lstrip(), encoding="utf-8")
            self.assertIn("SDD164", {item.code for item in self.validate(root)})

            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=root, check=True, capture_output=True)
            spec_path.unlink()
            findings = [item for item in self.validate(root) if item.code == "SDD154"]
            self.assertTrue(any("worktree" in item.message for item in findings))

    def test_approved_open_questions_require_nonblocking_marker_and_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            blocking = spec_document().replace("- None.", "- Which backend?")
            write(root, "Specs/Feature/README.md", blocking)
            self.assertIn("SDD153", {item.code for item in self.validate(root)})

            unexplained = spec_document().replace(
                "- None.", "- Which backend? — **non-blocking**"
            )
            write(root, "Specs/Feature/README.md", unexplained)
            self.assertIn("SDD153", {item.code for item in self.validate(root)})

            nonblocking = spec_document().replace(
                "- None.",
                "- Which backend? — **non-blocking** — Either backend satisfies FR-01.",
            )
            write(root, "Specs/Feature/README.md", nonblocking)
            self.assertNotIn("SDD153", {item.code for item in self.validate(root)})

            wrapped = spec_document().replace(
                "- None.",
                "- Which backend? — **non-blocking** — Either backend\n"
                "          satisfies FR-01.",
            )
            write(root, "Specs/Feature/README.md", wrapped)
            self.assertNotIn("SDD153", {item.code for item in self.validate(root)})

            mixed = spec_document().replace(
                "- None.", "Which backend owns writes?\n        - None."
            )
            write(root, "Specs/Feature/README.md", mixed)
            self.assertIn("SDD153", {item.code for item in self.validate(root)})

            draft = blocking.replace("status: approved", "status: draft", 1)
            write(root, "Specs/Feature/README.md", draft)
            self.assertNotIn("SDD153", {item.code for item in self.validate(root)})

    def test_complete_phase_requires_verbatim_task_evidence_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            task_evidence = "Task proof with exact output."
            phase = phase_document(task_status="complete")
            phase = phase.replace("status: planned", "status: complete", 1)
            phase = phase.replace("- [ ] Implement it.", "- [x] Implement it.")
            phase = phase.replace("- [ ] AC-01", "- [x] AC-01")
            phase = phase.replace("Pending — not complete.", task_evidence, 1)
            phase = phase.replace("Pending — not complete.", "Task 1.1 omitted.", 1)
            write(root, "Plans/Feature/01-Build.md", phase)
            write(root, "Plans/Feature/README.md", plan_document(phase_status="complete"))
            self.assertIn("SDD157", {item.code for item in self.validate(root)})

            phase = phase.replace(
                "Task 1.1 omitted.",
                f"### Task 1.1 Evidence Rollup\n        {task_evidence}",
            )
            write(root, "Plans/Feature/01-Build.md", phase)
            codes = {item.code for item in self.validate(root)}
            self.assertNotIn("SDD157", codes)
            self.assertNotIn("SDD020", codes)

            duplicate = phase + f"\n        ### Task 1.1 Evidence Rollup\n        {task_evidence}\n"
            write(root, "Plans/Feature/01-Build.md", duplicate)
            self.assertIn("SDD157", {item.code for item in self.validate(root)})

    def test_complete_plan_requires_child_ids_and_evidence_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            row = "| `pytest` | `/repo` | PASS (`exit 0`) | Behavior passed. |"
            table = (
                "| Command | Working directory | Result | Observable evidence |\n"
                "|---|---|---|---|\n" + row
            )
            indented_table = table.replace("\n", "\n        ")
            phase = phase_document(task_status="complete")
            phase = phase.replace("status: planned", "status: complete", 1)
            phase = phase.replace("- [ ] Implement it.", "- [x] Implement it.")
            phase = phase.replace("- [ ] AC-01", "- [x] AC-01")
            phase = phase.replace("Pending — not complete.", indented_table, 1)
            phase = phase.replace(
                "Pending — not complete.",
                f"### Task 1.1 Evidence Rollup\n        {indented_table}",
                1,
            )
            write(root, "Plans/Feature/01-Build.md", phase)
            plan = plan_document(phase_status="complete").replace(
                "status: active", "status: complete", 1
            )
            plan = plan.replace(
                "Pending — not complete.",
                f"<!--\n        ### Phase 1 Evidence Rollup\n        {indented_table}\n"
                f"        ### Task 1.1 Evidence Rollup\n        {indented_table}\n        -->",
            )
            write(root, "Plans/Feature/README.md", plan)
            self.assertIn("SDD158", {item.code for item in self.validate(root)})

            plan = plan.replace(
                f"<!--\n        ### Phase 1 Evidence Rollup\n        {indented_table}\n"
                f"        ### Task 1.1 Evidence Rollup\n        {indented_table}\n        -->",
                f"### Phase 1 Evidence Rollup\n        {indented_table}\n"
                f"        ### Task 1.1 Evidence Rollup\n        {indented_table}",
            )
            write(root, "Plans/Feature/README.md", plan)
            codes = {item.code for item in self.validate(root)}
            self.assertNotIn("SDD158", codes)
            self.assertNotIn("SDD020", codes)

    def test_fenced_required_heading_is_not_a_real_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            plan = plan_document().replace(
                "## Plan Completion Evidence\n        Pending — not complete.",
                "````markdown\n        ## Plan Completion Evidence\n"
                "        Pending — not complete.\n        ````",
            )
            write(root, "Plans/Feature/README.md", plan)
            findings = [item for item in self.validate(root) if item.code == "SDD020"]
            self.assertTrue(
                any("Plan Completion Evidence" in item.message for item in findings)
            )

    def test_dirty_git_snapshot_matches_changed_and_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            (root / "tracked.txt").write_text("base", encoding="utf-8")
            base = self.commit_all(root)
            (root / "tracked.txt").write_text("changed", encoding="utf-8")
            (root / "untracked.txt").write_text("new", encoding="utf-8")

            tracked, error = sdd_validate.worktree_snapshot_entry(root, b"tracked.txt", base)
            self.assertIsNone(error)
            assert tracked
            state, mode, size, digest = tracked
            manifest = (
                "sdd-dirty-snapshot-v1\n"
                f"base\t{base}\n"
                f"entry\t{state}\t{mode}\t{size}\t{digest}\ttracked.txt\n"
            ).encode()
            errors = sdd_validate.compare_dirty_git_snapshot(
                root / "snapshot.manifest", manifest, root, base, set()
            )
            self.assertTrue(any("omits changed paths: untracked.txt" in item for item in errors))

            untracked, error = sdd_validate.worktree_snapshot_entry(root, b"untracked.txt", base)
            self.assertIsNone(error)
            assert untracked
            state, mode, size, digest = untracked
            complete = manifest + (
                f"entry\t{state}\t{mode}\t{size}\t{digest}\tuntracked.txt\n"
            ).encode()
            self.assertEqual(
                [],
                sdd_validate.compare_dirty_git_snapshot(
                    root / "snapshot.manifest", complete, root, base, set()
                ),
            )

            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "advance head",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            (root / "tracked.txt").write_text("changed again", encoding="utf-8")
            errors = sdd_validate.compare_dirty_git_snapshot(
                root / "snapshot.manifest", complete, root, base, set()
            )
            self.assertTrue(any("differs from worktree" in item for item in errors))

    def test_snapshot_paths_modes_and_declared_ignored_inputs_are_checked(self) -> None:
        self.assertFalse(sdd_validate.valid_encoded_path("%2E%2E/outside"))
        self.assertFalse(sdd_validate.valid_encoded_path("%2Ftmp"))
        self.assertIsNotNone(sdd_validate.parse_inventory_paths("none")[1])
        self.assertIsNotNone(sdd_validate.parse_inventory_paths("arbitrary text")[1])
        self.assertEqual(
            ({"ignored.cfg"}, None),
            sdd_validate.parse_inventory_paths(
                "paths: `ignored.cfg`; sha256 recorded by capture tool"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitignore").write_text("ignored.cfg\nruntime/\n", encoding="utf-8")
            tracked = root / "tracked.txt"
            tracked.write_text("base", encoding="utf-8")
            base = self.commit_all(root)
            tracked.chmod(0o600)
            ignored = root / "ignored.cfg"
            ignored.write_text("ignored input", encoding="utf-8")

            errors = sdd_validate.compare_dirty_git_snapshot(
                root / "snapshot.manifest",
                f"sdd-dirty-snapshot-v1\nbase\t{base}\n".encode(),
                root,
                base,
                set(),
                {"ignored.cfg"},
            )
            self.assertTrue(any("ignored.cfg" in item for item in errors))
            self.assertTrue(any("tracked.txt" in item for item in errors))

            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "config.json").write_text("runtime input", encoding="utf-8")
            runtime_mode = f"{runtime.lstat().st_mode & 0o177777:06o}"
            directory_only = (
                "sdd-dirty-snapshot-v1\n"
                f"base\t{base}\n"
                f"directory\t{runtime_mode}\truntime\n"
            ).encode()
            errors = sdd_validate.compare_dirty_git_snapshot(
                root / "snapshot.manifest",
                directory_only,
                root,
                base,
                set(),
                {"runtime"},
                {"runtime"},
            )
            self.assertTrue(any("runtime/config.json" in item for item in errors))

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

    def test_scoped_validation_follows_transitive_related_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            spec_path = root / "Specs" / "Feature" / "README.md"
            spec_path.write_text(
                spec_path.read_text(encoding="utf-8").replace(
                    "related: []", "related: [Designs/Feature]", 1
                ),
                encoding="utf-8",
            )
            design = """
            ---
            title: Feature Design
            type: design
            status: approved
            created: 2026-07-23
            updated: 2026-07-23
            tags: [feature]
            related: [Research/legacy.txt]
            ---
            # Feature Design
            ## Overview
            Feature design.
            ## Design Decisions
            Decisions.
            ## Error Handling
            Errors.
            ## Testing Strategy
            Tests.
            ## Migration / Rollout
            Rollout.
            """
            write(root, "Designs/Feature/README.md", design)
            write(
                root,
                "Designs/Other/README.md",
                design.replace("Feature Design", "Other Design"),
            )
            legacy = root / "Research" / "legacy.txt"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text("not a discoverable SDD artifact\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(root),
                    "--scope",
                    "Plans/Feature/README.md",
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual(
                {
                    "Plans/Feature/README.md",
                    "Plans/Feature/01-Build.md",
                    "Specs/Feature/README.md",
                    "Designs/Feature/README.md",
                },
                set(payload["artifacts_in_scope"]),
            )
            self.assertTrue(
                any(item["path"] == "Designs/Feature/README.md" for item in payload["diagnostics"])
            )
            self.assertFalse(
                any(item["path"] == "Designs/Other/README.md" for item in payload["diagnostics"])
            )
            self.assertNotIn("Research/legacy.txt", payload["artifacts_in_scope"])

    def test_scope_aliases_resolve_or_report_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            write(
                root,
                "Research/Topic.md",
                """
                ---
                title: Topic
                type: research
                status: active
                created: 2026-07-23
                updated: 2026-07-23
                tags: [topic]
                related: []
                ---
                # Topic
                ## Context
                Context.
                ## Findings
                Findings.
                ## Analysis
                Analysis.
                ## Open Questions
                None.
                """,
            )
            validator = sdd_validate.Validator(root, root)
            diagnostics = validator.run()
            alias = sdd_validate.resolve_scope(validator, "Specs/Feature/README")
            self.assertIsNone(alias.error)
            self.assertIn("Specs/Feature/README.md", alias.artifacts)

            flat = sdd_validate.resolve_scope(validator, "Topic")
            self.assertIsNone(flat.error)
            self.assertEqual(frozenset({"Research/Topic.md"}), flat.artifacts)

            ambiguous = sdd_validate.resolve_scope(validator, "Feature")
            self.assertIn("ambiguous", ambiguous.error or "")
            self.assertEqual(
                ("Plans/Feature", "Specs/Feature/README.md"),
                ambiguous.roots,
            )

            deleted = sdd_validate.resolve_scope(
                validator,
                "Specs/Deleted/README.md",
                diagnostics
                + [
                    sdd_validate.Diagnostic(
                        "error",
                        "SDD164",
                        "Specs/Deleted/README.md",
                        1,
                        "deleted",
                        "restore",
                    )
                ],
            )
            self.assertIsNone(deleted.error)
            self.assertEqual(("Specs/Deleted/README.md",), deleted.roots)

            (root / "README.md").write_text("ordinary repository file\n", encoding="utf-8")
            for unsafe in ("README.md", "../outside", str(root / "README.md")):
                self.assertIsNotNone(
                    sdd_validate.resolve_scope(validator, unsafe, diagnostics).error
                )

            write(root, "Plans/Mixed/README.md", plan_document().replace("Feature Plan", "Mixed Plan"))
            write(root, "Specs/Mixed/README.md", "not frontmatter\n")
            mixed_validator = sdd_validate.Validator(root, root)
            mixed_diagnostics = mixed_validator.run()
            mixed = sdd_validate.resolve_scope(
                mixed_validator, "Mixed", mixed_diagnostics
            )
            self.assertIn("ambiguous", mixed.error or "")
            self.assertEqual(
                ("Plans/Mixed", "Specs/Mixed/README.md"),
                mixed.roots,
            )

    def test_scoped_malformed_artifact_keeps_parse_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            malformed = root / "Plans" / "Feature" / "02-Broken.md"
            malformed.write_text("not frontmatter\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(root),
                    "--scope",
                    "Plans/Feature",
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertTrue(
                any(
                    item["path"] == "Plans/Feature/02-Broken.md"
                    and item["code"] == "SDD004"
                    for item in payload["diagnostics"]
                )
            )
            self.assertNotIn("Plans/Feature/02-Broken.md", payload["artifacts_in_scope"])

            malformed_spec = root / "Specs" / "Feature" / "extra.md"
            malformed_spec.write_text("not frontmatter\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(root),
                    "--scope",
                    "Specs/Feature",
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertTrue(
                any(item["path"] == "Specs/Feature/extra.md" for item in payload["diagnostics"])
            )

    def test_graph_selection_preserves_global_diagnostics_and_candidates(self) -> None:
        diagnostics = [
            sdd_validate.Diagnostic("error", "SDD020", "Designs/Feature/README.md", 1, "feature", "fix"),
            sdd_validate.Diagnostic("error", "SDD020", "Designs/Other/README.md", 1, "other", "fix"),
            sdd_validate.Diagnostic("candidate", "DLG060", "Decisions/decisions.md", 1, "candidate", "judge"),
            sdd_validate.Diagnostic("error", "SDD145", "Decisions/decisions.md", 1, "decision scope", "fix"),
            sdd_validate.Diagnostic("operational", "SDD999", "outside", 1, "operation", "repair"),
        ]
        selected = sdd_validate.select(
            diagnostics,
            "Plans/Feature",
            {"Plans/Feature/README.md", "Designs/Feature/README.md"},
        )
        self.assertEqual(
            {"feature", "candidate", "decision scope", "operation"},
            {item.message for item in selected},
        )

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
            - Fallback reason: `fixture exercises an explicitly selected dirty-Git fallback`
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
            self.commit_all(root)
            codes = {
                item.code
                for item in sdd_validate.Validator(root, root, "historical").run()
            }
            self.assertFalse({"SDD070", "SDD071", "SDD072", "SDD074", "SDD075", "SDD076", "SDD077", "SDD078", "SDD079", "SDD159"} & codes)

    def test_dirty_snapshot_digest_wiring_accepts_current_git_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            source = root / "source.txt"
            source.write_text("base", encoding="utf-8")
            base = self.commit_all(root)
            source.write_text("changed", encoding="utf-8")

            entry, error = sdd_validate.worktree_snapshot_entry(root, b"source.txt", base)
            self.assertIsNone(error)
            assert entry
            state, mode, size, digest = entry
            snapshot_path = root / "evidence" / "snapshot.manifest"
            object_path = Path(f"{snapshot_path}.contents") / digest
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(source.read_bytes())
            exclusions = {
                "evidence/snapshot.manifest",
                f"evidence/snapshot.manifest.contents/{digest}",
            }
            snapshot = (
                "sdd-dirty-snapshot-v1\n"
                f"base\t{base}\n"
                + "".join(f"exclude\t{value}\n" for value in sorted(exclusions))
                + f"entry\t{state}\t{mode}\t{size}\t{digest}\tsource.txt\n"
            ).encode()
            snapshot_path.write_bytes(snapshot)

            validator = sdd_validate.Validator(root, root, "current")
            validator._discover()
            artifact = validator.by_path["Plans/Feature/README.md"]
            validator._digest(
                artifact,
                "Plan Completion Evidence",
                f"{hashlib.sha256(snapshot).hexdigest()} at evidence/snapshot.manifest",
                1,
                capture_kind="snapshot",
                expected_vcs="git",
                expected_revision=f"{base}-dirty",
                expected_exclusions=exclusions,
                expected_ignored=set(),
                expected_directories=set(),
            )
            self.assertFalse(
                {"SDD079", "SDD159"} & {item.code for item in validator.out}
            )

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
        fenced = """
            ````markdown
            | Command | Working directory | Result | Observable evidence |
            |---|---|---|---|
            | `fake` | `/repo` | PASS (`exit 0`) | Only an example. |
            ````
        """
        self.assertEqual([], sdd_validate.evidence_rows(textwrap.dedent(fenced)))
        rollup = """
            ### Task 1.1 Evidence Rollup
            ```text
            exact captured output
            ```
        """
        bodies = sdd_validate.rollup_bodies(textwrap.dedent(rollup), "Task 1.1 Evidence Rollup")
        self.assertEqual(1, len(bodies))
        self.assertIn("```text\nexact captured output\n```", bodies[0])
        duplicate = textwrap.dedent(rollup + rollup)
        self.assertEqual(
            2,
            len(sdd_validate.rollup_bodies(duplicate, "Task 1.1 Evidence Rollup")),
        )
        task_body = """
            ### Notes
            ````markdown
            ### Completion Evidence
            Pending — not complete.
            ````
            ### Completion Evidence
            proof <!-- annotation --> retained
        """
        evidence = sdd_validate.completion_evidence_body(textwrap.dedent(task_body))
        self.assertEqual("proof  retained", evidence)
        inline_rollup = """
            ### Task 1.1 Evidence Rollup
            proof <!-- annotation --> retained
        """
        self.assertEqual(
            [evidence],
            sdd_validate.rollup_bodies(
                textwrap.dedent(inline_rollup), "Task 1.1 Evidence Rollup"
            ),
        )

    def test_fenced_spec_definition_does_not_preserve_append_only_id(self) -> None:
        source = spec_document().replace(
            "- **FR-01**: Do the thing.",
            "````markdown\n        - **FR-01**: Do the thing.\n        ````\n"
            "        - **FR-02**: Replacement.",
        )
        self.assertNotIn("FR-01", sdd_validate.spec_retained_ids(textwrap.dedent(source)))

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

    def test_clean_git_identity_checks_immutable_ancestor_commit(self) -> None:
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
                plan, revision, "Plan Completion Evidence", 1, True
            )
            self.assertEqual([], validator.out)
            (root / "changed.txt").write_text("changed", encoding="utf-8")
            validator._verify_clean_git_identity(
                plan, revision, "Plan Completion Evidence", 1, True
            )
            self.assertEqual([], validator.out)

    def test_clean_git_evidence_uses_commits_without_evidence_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            implementation_revision = self.commit_all(root)
            block = f"""
            - Verified: 2026-07-23
            - Repository: `{root}`
            - VCS: `git`
            - Revision / base: `{implementation_revision}`
            - Identity recheck: `git diff-tree --exit-code {implementation_revision}`, 2026-07-23T12:00:00Z, matched commit tree

            | Command | Working directory | Result | Observable evidence |
            |---|---|---|---|
            | `python3 -m unittest` | `{root}` | PASS (`exit 0`) | Named behavior passed. |
            """
            phase = phase_document(task_status="complete")
            phase = phase.replace("- [ ] Implement it.", "- [x] Implement it.")
            indented_block = textwrap.dedent(block).strip().replace("\n", "\n        ")
            phase = phase.replace(
                "Pending — not complete.", indented_block, 1
            )
            write(root, "Plans/Feature/01-Build.md", phase)
            subprocess.run(["git", "add", "Plans/Feature/01-Build.md"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "Record task completion",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )

            findings = sdd_validate.Validator(root, root, "current").run()
            evidence_findings = {
                item.code for item in findings if "Task 1.1 Completion Evidence" in item.message
            }
            self.assertFalse({"SDD071", "SDD072", "SDD074"} & evidence_findings)
            self.assertFalse((root / "evidence").exists())

            phase_path = root / "Plans" / "Feature" / "01-Build.md"
            phase_path.write_text(
                phase_path.read_text(encoding="utf-8").replace(
                    "Named behavior passed.", "Uncommitted evidence edit."
                ),
                encoding="utf-8",
            )
            findings = sdd_validate.Validator(root, root, "current").run()
            self.assertTrue(
                any("differs from its committed section" in item.message for item in findings)
            )

    def test_uncommitted_task_completion_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            implementation_revision = self.commit_all(root)
            block = f"""
            - Verified: 2026-07-23
            - Repository: `{root}`
            - VCS: `git`
            - Revision / base: `{implementation_revision}`
            - Identity recheck: `git diff-tree --exit-code {implementation_revision}`, 2026-07-23T12:00:00Z, matched commit tree

            | Command | Working directory | Result | Observable evidence |
            |---|---|---|---|
            | `python3 -m unittest` | `{root}` | PASS (`exit 0`) | Named behavior passed. |
            """
            indented = textwrap.dedent(block).strip().replace("\n", "\n        ")
            phase = phase_document(task_status="in-progress").replace(
                "Pending — not complete.", indented, 1
            )
            write(root, "Plans/Feature/01-Build.md", phase)
            subprocess.run(["git", "add", "Plans/Feature/01-Build.md"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "Stage evidence"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            phase_path = root / "Plans" / "Feature" / "01-Build.md"
            source = phase_path.read_text(encoding="utf-8")
            source = source.replace("status: in-progress", "status: complete", 1)
            source = source.replace("- [ ] Implement it.", "- [x] Implement it.")
            phase_path.write_text(source, encoding="utf-8")

            findings = sdd_validate.Validator(root, root, "current").run()
            self.assertTrue(
                any("lifecycle completion is not committed" in item.message for item in findings)
            )

    def test_clean_git_rejects_every_fallback_only_field(self) -> None:
        body = """
        - Verified: 2026-07-23
        - Repository: `/tmp/repo`
        - VCS: `git`
        - Revision / base: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
        - Identity recheck: `git`, 2026-07-23T12:00:00Z, matched commit
        - Ignored inputs: `none with inspection basis`

        | Tool / inspection | Context | Result | Observable evidence |
        |---|---|---|---|
        | `inspection` | `repo` | PASS | Clean commit inspected. |
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            validator = sdd_validate.Validator(root, root, "historical")
            validator._discover()
            artifact = validator.by_path["Plans/Feature/README.md"]
            validator._evidence(
                artifact,
                "in-progress",
                "Plan Completion Evidence",
                1,
                textwrap.dedent(body),
            )
            self.assertTrue(any(item.code == "SDD074" for item in validator.out))

    def test_phase_completion_requires_committed_parent_plan_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.commit_all(root)
            evidence = """
            - Verified: 2026-07-23
            - Repository: `/tmp/example`
            - VCS: `git`
            - Revision / base: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
            - Identity recheck: `git aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`, 2026-07-23T12:00:00Z, matched commit

            | Tool / inspection | Context | Result | Observable evidence |
            |---|---|---|---|
            | `inspection` | `phase` | PASS | Phase behavior passed. |
            """
            indented = textwrap.dedent(evidence).strip().replace("\n", "\n        ")
            phase = phase_document()
            phase = phase.replace("status: planned", "status: complete", 1)
            phase = phase.replace("- [ ] AC-01", "- [x] AC-01")
            phase = phase.replace("Pending — not complete.", indented, 2)
            write(root, "Plans/Feature/01-Build.md", phase)
            subprocess.run(["git", "add", "Plans/Feature/01-Build.md"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "Complete phase artifact"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            plan_path = root / "Plans" / "Feature" / "README.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8").replace(
                    "status: planned", "status: complete", 1
                ),
                encoding="utf-8",
            )
            validator = sdd_validate.Validator(root, root, "current")
            validator._discover()
            artifact = validator.by_path["Plans/Feature/01-Build.md"]
            validator._verify_evidence_committed(
                artifact,
                "Phase Completion Evidence",
                textwrap.dedent(evidence).strip(),
                1,
            )
            self.assertTrue(
                any("lifecycle completion is not committed" in item.message for item in validator.out)
            )

    def test_deleted_or_nested_fallback_capture_reports_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            capture = root / "capture.bin"
            capture.write_bytes(b"capture")
            self.commit_all(root)
            capture.unlink()
            validator = sdd_validate.Validator(root, root, "current")
            validator._discover()
            artifact = validator.by_path["Plans/Feature/README.md"]
            validator._verify_capture_committed(
                artifact, "capture.bin", "Plan Completion Evidence", 1
            )
            self.assertTrue(any("missing from the worktree" in item.message for item in validator.out))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_tree(root)
            self.commit_all(root)
            nested = root / "nested"
            nested.mkdir()
            subprocess.run(["git", "init"], cwd=nested, check=True, capture_output=True)
            (nested / "capture.bin").write_bytes(b"capture")
            subprocess.run(["git", "add", "capture.bin"], cwd=nested, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "nested capture"],
                cwd=nested,
                check=True,
                capture_output=True,
            )
            validator = sdd_validate.Validator(root, root, "current")
            validator._discover()
            artifact = validator.by_path["Plans/Feature/README.md"]
            validator._verify_capture_committed(
                artifact, "nested/capture.bin", "Plan Completion Evidence", 1
            )
            self.assertTrue(
                any("not in the lifecycle artifact's Git worktree" in item.message for item in validator.out)
            )

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
