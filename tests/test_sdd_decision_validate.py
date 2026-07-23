from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "sdd_decision_validate.py"
SPEC = importlib.util.spec_from_file_location("sdd_decision_validate", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)
FULL_SPEC = importlib.util.spec_from_file_location("sdd_validate_with_decisions", PLUGIN_ROOT / "scripts" / "sdd_validate.py")
assert FULL_SPEC and FULL_SPEC.loader
full_validator = importlib.util.module_from_spec(FULL_SPEC)
sys.modules[FULL_SPEC.name] = full_validator
FULL_SPEC.loader.exec_module(full_validator)


def entry(identifier: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identifier,
        "kind": "decision",
        "status": "accepted",
        "date": "2026-07-23",
        "decided_by": "user",
        "statement": f"Statement for {identifier}.",
        "rejected": [],
        "rationale": "A concrete rationale.",
        "scope": [],
        "tags": ["test"],
    }
    value.update(overrides)
    return value


def write_ledger(path: Path, decisions: list[object], status: str = "active", body: str = "# Decision Ledger\n") -> None:
    metadata = {
        "title": "Decision Ledger",
        "type": "decision-log",
        "status": status,
        "created": "2026-07-23",
        "updated": "2026-07-23",
        "tags": ["decisions"],
        "related": [],
        "decisions": decisions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


def codes(path: Path, history: bool = False) -> set[str]:
    diagnostics, _, _ = validator.validate(path, history=history)
    return {item.code for item in diagnostics}


class DecisionValidatorTests(unittest.TestCase):
    def test_skills_and_convention_require_the_validator(self) -> None:
        for relative in (
            "shared/decision-log.md",
            "skills/sdd-decide/SKILL.md",
            "skills/sdd-decision-log/SKILL.md",
            "skills/sdd-validate/SKILL.md",
            "README.md",
        ):
            text = (PLUGIN_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("sdd_decision_validate.py", text, relative)
        decisions = (PLUGIN_ROOT / "Decisions" / "decisions.md").read_text(encoding="utf-8")
        self.assertIn("id: D-0010", decisions)
        self.assertIn("bundled deterministic validator", decisions)

    def test_valid_ledger_and_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            write_ledger(ledger, [entry("D-0001")], body="# Decision Ledger\n\n## D-0001 — Context\nMore detail.\n")
            self.assertEqual(codes(ledger), set())
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(ledger), "--format", "json", "--no-history"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["decisions_inspected"], 1)

    def test_instantiated_bundled_template_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            template = (PLUGIN_ROOT / "shared" / "templates" / "decision-log.md").read_text(encoding="utf-8")
            ledger.parent.mkdir(parents=True)
            ledger.write_text(template.replace("{{DATE}}", "2026-07-23"), encoding="utf-8")
            self.assertEqual(codes(ledger), set())

    def test_entry_schema_types_dates_scope_and_body_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            malformed = entry(
                "bad",
                kind="answered-question",
                date="2026-02-30",
                statement=42,
                rejected="option",
                scope=["../outside"],
                reversibility="sometimes",
                refresh_when=["event"],
            )
            write_ledger(ledger, [malformed], body="# Decision Ledger\n\n## D-9999 — Stale\nDetail.\n")
            self.assertTrue(
                {"DLG023", "DLG029", "DLG030", "DLG031", "DLG027", "DLG033", "DLG034", "DLG035", "DLG040"}
                <= codes(ledger)
            )

    def test_archives_participate_in_duplicate_and_lifecycle_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Decisions"
            ledger = root / "decisions.md"
            archive = root / "archive-2025.md"
            write_ledger(ledger, [entry("D-0001")])
            write_ledger(archive, [entry("D-0001")], status="archived")
            self.assertTrue({"DLG037", "DLG050"} <= codes(ledger))

    def test_supersession_links_states_and_cycles_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            valid = [
                entry("D-0001", status="superseded", superseded_by="D-0002"),
                entry("D-0002", supersedes="D-0001"),
            ]
            write_ledger(ledger, valid)
            self.assertFalse({"DLG051", "DLG052", "DLG053", "DLG055", "DLG056", "DLG057", "DLG058", "DLG059"} & codes(ledger))

            chain = [
                entry("D-0001", status="superseded", superseded_by="D-0002"),
                entry("D-0002", status="superseded", supersedes="D-0001", superseded_by="D-0003"),
                entry("D-0003", supersedes="D-0002"),
            ]
            write_ledger(ledger, chain)
            self.assertFalse({"DLG053", "DLG058", "DLG059", "DLG066"} & codes(ledger))

            cyclic = [
                entry("D-0001", status="superseded", supersedes="D-0002", superseded_by="D-0002"),
                entry("D-0002", status="superseded", supersedes="D-0001", superseded_by="D-0001"),
            ]
            write_ledger(ledger, cyclic)
            self.assertIn("DLG059", codes(ledger))

    def test_structural_collision_candidates_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            decisions = [
                entry("D-0001", kind="answered-question", question="Which database?", statement="Use PostgreSQL.", rejected=["DynamoDB"]),
                entry("D-0002", status="proposed", kind="answered-question", question="Which database?", statement="Use DynamoDB."),
            ]
            write_ledger(ledger, decisions)
            self.assertTrue({"DLG060", "DLG061"} <= codes(ledger))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(ledger), "--format", "json", "--no-history"],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["valid"])
            self.assertTrue(all(item["severity"] == "candidate" for item in payload["diagnostics"]))

            archive = ledger.parent / "archive-2025.md"
            write_ledger(
                archive,
                [entry("D-0003", status="rejected", statement="Use MongoDB.")],
                status="archived",
            )
            write_ledger(ledger, [entry("D-0001", statement="Use MongoDB for persistence.")])
            self.assertIn("DLG063", codes(ledger))

    def test_git_history_protects_accepted_entries_but_allows_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            original = entry("D-0001")
            write_ledger(ledger, [original])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            write_ledger(ledger, [{**original, "statement": "Mutated."}, entry("D-0002")])
            self.assertIn("DLG071", codes(ledger, history=True))

            write_ledger(ledger, [original, entry("D-0002")])
            self.assertNotIn("DLG071", codes(ledger, history=True))

    def test_git_history_retains_rejected_and_superseded_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            old = entry("D-0001", status="rejected")
            write_ledger(ledger, [old])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            write_ledger(ledger, [{**old, "rationale": "Changed."}])
            self.assertIn("DLG073", codes(ledger, history=True))

    def test_git_history_detects_deleted_and_staged_archive_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            archive = ledger.parent / "archive-2025.md"
            write_ledger(archive, [entry("D-0001", status="rejected")], status="archived")
            write_ledger(ledger, [entry("D-0002")])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            archive.unlink()
            self.assertIn("DLG070", codes(ledger, history=True))

            archive_path = "Decisions/archive-2025.md"
            subprocess.run(["git", "restore", archive_path], cwd=root, check=True)
            subprocess.run(["git", "rm", "--cached", archive_path], cwd=root, check=True, capture_output=True)
            self.assertIn("DLG070", codes(ledger, history=True))

    def test_history_spans_canonical_locations_and_staged_new_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "DECISIONS.md"
            write_ledger(external, [entry("D-0001")])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            external.unlink()
            internal = root / "Decisions" / "decisions.md"
            write_ledger(internal, [entry("D-0002")])
            self.assertIn("DLG070", codes(internal, history=True))

            internal.unlink()
            subprocess.run(["git", "restore", "DECISIONS.md"], cwd=root, check=True)
            write_ledger(external, [entry("D-0001"), entry("D-0002")])
            subprocess.run(["git", "add", "DECISIONS.md"], cwd=root, check=True)
            write_ledger(external, [entry("D-0001")])
            self.assertIn("DLG074", codes(external, history=True))

            write_ledger(internal, [entry("D-0002")])
            self.assertIn("DLG074", codes(external, history=True))

    def test_unborn_repository_allows_first_ledger_and_git_failures_do_not_silently_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            write_ledger(ledger, [entry("D-0001")])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            self.assertNotIn("DLG075", codes(ledger, history=True))
            with mock.patch.object(validator, "git_ledger_paths", return_value=None):
                # Create HEAD so enumeration is required.
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                diagnostics, _, _ = validator.validate(ledger, history=True)
            self.assertIn("DLG076", {item.code for item in diagnostics})
            self.assertIn("operational", {item.severity for item in diagnostics if item.code == "DLG076"})

    def test_first_ledger_compares_new_staged_entries_with_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            ledger = root / "Decisions" / "decisions.md"
            write_ledger(ledger, [entry("D-0001")])
            subprocess.run(["git", "add", "Decisions/decisions.md"], cwd=root, check=True)
            write_ledger(ledger, [entry("D-0001", statement="Different worktree statement.")])
            self.assertIn("DLG074", codes(ledger, history=True))

    def test_historical_duplicate_ids_require_preserving_and_renumbering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            archive = ledger.parent / "archive-2025.md"
            write_ledger(ledger, [entry("D-0001")])
            write_ledger(archive, [entry("D-0001", status="rejected")], status="archived")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            archive.unlink()
            self.assertIn("DLG077", codes(ledger, history=True))

    def test_duplicate_yaml_keys_timestamps_provenance_and_scope_syntax_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                """---
title: Decision Ledger
type: decision-log
status: active
created: 2026-07-23T12:00:00Z
updated: 2026-07-23
tags: []
related: []
decisions: []
decisions: []
---
# Decision Ledger
""",
                encoding="utf-8",
            )
            self.assertIn("DLG005", codes(ledger))

            write_ledger(
                ledger,
                [entry("D-0001", decided_by="agent", status="accepted", scope=["C:outside"]), entry("D-0002", decided_by="user-approved", status="proposed")],
            )
            self.assertTrue({"DLG033", "DLG041", "DLG044"} <= codes(ledger))
            ledger.write_text(ledger.read_text().replace("created: '2026-07-23'", "created: 2026-07-23T12:00:00Z"), encoding="utf-8")
            self.assertIn("DLG014", codes(ledger))

    def test_sequential_ids_and_entry_order_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            write_ledger(ledger, [entry("D-0001"), entry("D-0003")])
            self.assertIn("DLG064", codes(ledger))
            write_ledger(ledger, [entry("D-0002"), entry("D-0001")])
            self.assertIn("DLG065", codes(ledger))
            write_ledger(ledger, [entry("D-999999999999999999999999")])
            self.assertIn("DLG023", codes(ledger))

    def test_supersession_must_move_forward_in_id_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            write_ledger(
                ledger,
                [
                    entry("D-0001", supersedes="D-0002", date="2026-07-22"),
                    entry("D-0002", status="superseded", superseded_by="D-0001", date="2026-07-23"),
                ],
            )
            self.assertTrue({"DLG067", "DLG068"} <= codes(ledger))

    def test_nested_external_ledger_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested" / "DECISIONS.md"
            write_ledger(nested, [])
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            self.assertIn("DLG042", codes(nested))
            link = root / "DECISIONS.md"
            link.symlink_to(nested)
            self.assertIn("DLG019", codes(link))

    def test_archive_only_surface_requires_canonical_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "Decisions" / "archive-2025.md"
            write_ledger(archive, [entry("D-0001", status="rejected")], status="archived")
            self.assertIn("DLG045", codes(archive))

    def test_full_sdd_validator_composes_focused_ledger_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            write_ledger(ledger, [entry("D-0001", scope=["../outside"])])
            result = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "scripts" / "sdd_validate.py"), "--root", str(root), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("DLG033", {item["code"] for item in json.loads(result.stdout)["diagnostics"]})

    def test_full_sdd_validator_preserves_nonfatal_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "Decisions" / "decisions.md"
            write_ledger(
                ledger,
                [
                    entry("D-0001", kind="answered-question", question="Which database?", statement="Use PostgreSQL."),
                    entry("D-0002", status="proposed", decided_by="agent", kind="answered-question", question="Which database?", statement="Use SQLite."),
                ],
            )
            result = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "scripts" / "sdd_validate.py"), "--root", str(root), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["valid"])
            self.assertIn("DLG060", {item["code"] for item in payload["diagnostics"] if item["severity"] == "candidate"})

    def test_scoped_full_validation_keeps_focused_ledger_diagnostics(self) -> None:
        finding = full_validator.Diagnostic(
            "error",
            "DLG033",
            "/external/repository/DECISIONS.md",
            1,
            "Unsafe scope.",
            "Use a relative scope.",
        )
        self.assertEqual(full_validator.select([finding], "Plans/Feature"), [finding])

    def test_invalid_utf8_is_operational_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "Decisions" / "decisions.md"
            ledger.parent.mkdir(parents=True)
            ledger.write_bytes(b"\xff\xfe")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(ledger), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["diagnostics"][0]["severity"], "operational")

    def test_missing_ledger_is_operational_error(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "/definitely/missing/DECISIONS.md", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ledger does not exist", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
