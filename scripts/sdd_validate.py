#!/usr/bin/env python3
"""Deterministically validate sdd-planner Markdown artifacts."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from urllib.parse import unquote, unquote_to_bytes, urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from sdd_decision_validate import validate as validate_decision_ledgers
except ImportError:
    from scripts.sdd_decision_validate import validate as validate_decision_ledgers

try:
    import yaml
except ImportError:
    print(
        "sdd-validate: PyYAML is required; install it with "
        "`python3 -m pip install -r <plugin-root>/requirements.txt`",
        file=sys.stderr,
    )
    raise SystemExit(2)


STATUS = {
    "research": {"draft", "active", "archived"},
    "brainstorm": {"draft", "active", "archived"},
    "spec": {"draft", "review", "approved", "implemented", "superseded"},
    "design": {"draft", "review", "approved", "implemented", "superseded"},
    "plan": {"draft", "approved", "active", "complete", "archived"},
    "phase": {"planned", "in-progress", "complete", "blocked", "deferred"},
    "debrief": {"draft", "complete"},
    "retro": {"draft", "complete"},
    "diagram": {"draft", "active", "archived"},
    "decision-log": {"active", "archived"},
    "review": {"open", "resolved", "superseded"},
}
TASK_STATUS = {"planned", "in-progress", "complete", "blocked", "deferred"}
FINDING_STATUS = {"open", "fixed", "deferred", "rejected", "answered"}
DECISION_STATUS = {"proposed", "accepted", "rejected", "superseded"}
ARTIFACT_DIRS = ("Research", "Brainstorm", "Specs", "Designs", "Plans", "Decisions", "Retro", "Diagrams")
COMMON_FIELDS = ("title", "type", "status", "created", "updated")
PENDING = "Pending — not complete."
SHA256 = re.compile(r"\b([0-9a-fA-F]{64})\b")
IDS = {
    "FR": re.compile(r"\bFR-(\d{2,})\b"),
    "NFR": re.compile(r"\bNFR-(\d{2,})\b"),
    "AC": re.compile(r"\bAC-(\d{2,})\b"),
    "D": re.compile(r"\bD-(\d{4,})\b"),
}
DEFINITIONS = {
    "FR": re.compile(r"^\s*-\s+\*\*(FR-\d{2,})\*\*\s*:", re.MULTILINE),
    "NFR": re.compile(r"^\s*-\s+\*\*(NFR-\d{2,})\*\*\s*:", re.MULTILINE),
    "AC": re.compile(r"^\s*-\s+\[[ xX]\]\s+\*\*(AC-\d{2,})\*\*\s*:", re.MULTILINE),
}
NON_BLOCKING = re.compile(r"\*\*non-blocking\*\*", re.IGNORECASE)
REQUIRED_HEADINGS = {
    "research": ("Context", "Findings", "Analysis", "Open Questions"),
    "brainstorm": ("Problem Statement", "Ideas", "Evaluation", "Next Steps"),
    "spec": ("Overview", "Goals", "Non-Goals", "Requirements", "User Stories", "Acceptance Criteria", "Constraints", "Dependencies", "Open Questions"),
    "design": ("Overview", "Architecture", "Design Decisions", "Error Handling", "Testing Strategy", "Migration / Rollout"),
    "plan": ("Overview", "Architecture", "Key Decisions", "Dependencies", "Plan Completion Evidence"),
    "phase": ("Overview", "Acceptance Criteria", "Phase Completion Evidence"),
    "review": ("Findings", "Resolution Log"),
    "debrief": ("Decisions Made", "Requirements Assessment", "Deviations", "Risks & Issues Encountered", "Lessons Learned", "Impact on Subsequent Phases", "Skill Opportunities"),
}


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    path: str
    line: int
    message: str
    correction: str
    implicated: tuple[str, ...] = ()


@dataclass
class Artifact:
    path: Path
    rel: str
    meta: dict[str, Any]
    body: str
    source: str
    body_line: int

    @property
    def kind(self) -> str:
        return self.meta.get("type") if isinstance(self.meta.get("type"), str) else ""

    @property
    def status(self) -> str:
        return self.meta.get("status") if isinstance(self.meta.get("status"), str) else ""

    def line(self, text: str, body: bool = False) -> int:
        source = self.body if body else self.source
        offset = self.body_line - 1 if body else 0
        for number, value in enumerate(source.splitlines(), 1):
            if text in value:
                return number + offset
        return 1


@dataclass(frozen=True)
class ScopeSelection:
    artifacts: frozenset[str]
    roots: tuple[str, ...]
    error: str | None = None


class Validator:
    def __init__(self, root: Path, repo: Path, identity_mode: str = "auto") -> None:
        self.root = root.resolve()
        self.repo = repo.resolve()
        self.artifacts: list[Artifact] = []
        self.by_path: dict[str, Artifact] = {}
        self.tasks: dict[tuple[str, str], tuple[Artifact, dict[str, Any]]] = {}
        self.decisions: dict[tuple[str, str], tuple[Artifact, dict[str, Any]]] = {}
        self.spec_ids: dict[str, dict[str, set[str]]] = {}
        self.out: list[Diagnostic] = []
        self.identity_mode = identity_mode
        self.artifact_repos: dict[str, Path] = {}
        self.plan_repos: dict[str, Path] = {}
        self._configure_repositories()

    def error(self, artifact: Artifact | None, code: str, message: str, correction: str, line: int = 1, path: str | None = None, implicated: Iterable[str] = ()) -> None:
        self.out.append(Diagnostic("error", code, path or (artifact.rel if artifact else str(self.root)), line, message, correction, tuple(sorted(set(implicated)))))

    def candidate(self, artifact: Artifact | None, code: str, message: str, correction: str, line: int = 1, path: str | None = None) -> None:
        self.out.append(Diagnostic("candidate", code, path or (artifact.rel if artifact else str(self.root)), line, message, correction))

    def _configure_repositories(self) -> None:
        config = self.repo / "planning-config.json"
        if not config.is_file():
            return
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.error(None, "SDD000", f"Cannot parse `{config}`: {exc}", "Correct planning-config.json before validation.")
            return
        mappings = data.get("planMapping", {})
        repositories = data.get("repositories", {})
        if not isinstance(mappings, dict) or not isinstance(repositories, dict):
            self.error(None, "SDD000", "`planMapping` and `repositories` must be JSON objects.", "Correct planning-config.json repository mapping.")
            return
        for plan_name, repository_key in mappings.items():
            record = repositories.get(repository_key)
            raw_path = record.get("path") if isinstance(record, dict) else record
            if not isinstance(plan_name, str) or not isinstance(raw_path, str):
                self.error(None, "SDD000", f"Plan mapping `{plan_name}` does not resolve to a repository path.", "Add repositories.<key>.path for every plan mapping.")
                continue
            target = Path(raw_path)
            target = (target if target.is_absolute() else config.parent / target).resolve()
            if not target.is_dir():
                self.error(None, "SDD000", f"Mapped repository `{target}` for plan `{plan_name}` does not exist.", "Correct the mapping or create the target repository.")
                continue
            self.plan_repos[plan_name] = target

    def _repo_for_path(self, relative: str) -> Path:
        parts = Path(relative).parts
        if len(parts) >= 2 and parts[0] == "Plans":
            return self.plan_repos.get(parts[1], self.repo)
        return self.repo

    def _repo_for_artifact(self, artifact: Artifact) -> Path:
        return self.artifact_repos.get(artifact.rel, self._repo_for_path(artifact.rel))

    def _capture_path(self, artifact: Artifact, recorded: str) -> Path:
        value = Path(recorded)
        if value.is_absolute():
            return value.resolve()
        repository_candidate = (self._repo_for_artifact(artifact) / value).resolve()
        planning_candidate = (self.root / value).resolve()
        try:
            repository_candidate.relative_to(self.root)
            return repository_candidate
        except ValueError:
            return planning_candidate

    def run(self) -> list[Diagnostic]:
        self._discover()
        self._legacy_layouts()
        for artifact in self.artifacts:
            self._common(artifact)
        self._index()
        self._append_only_repository_history()
        for artifact in self.artifacts:
            self._headings(artifact)
            self._references(artifact)
            self._specific(artifact)
            self._citations(artifact)
        self._phase_ownership()
        self._graphs()
        self._traceability()
        self._decision_links()
        self._focused_decision_logs()
        return sorted(self.out, key=lambda item: (item.path, item.line, item.code, item.message))

    def _discover(self) -> None:
        if not self.root.is_dir():
            self.error(None, "SDD001", "Planning root is not a directory.", "Pass an existing planning root with --root.")
            return
        paths: set[Path] = set()
        for dirname in ARTIFACT_DIRS:
            directory = self.root / dirname
            if directory.is_dir():
                paths.update(directory.rglob("*.md"))
        for path in sorted(paths):
            artifact = self._parse(path)
            if artifact:
                self.artifacts.append(artifact)
                self.by_path[artifact.rel] = artifact
                self.artifact_repos[artifact.rel] = self._repo_for_path(artifact.rel)
        for key, repository in sorted({str(path): path for path in self.plan_repos.values()}.items()):
            if repository == self.repo:
                continue
            candidates = [repository / "DECISIONS.md", *sorted(repository.glob("archive-*.md"))]
            for path in candidates:
                if not path.is_file():
                    continue
                rel = f"@repo:{key}/{path.name}"
                artifact = self._parse(path, rel)
                if artifact:
                    self.artifacts.append(artifact)
                    self.by_path[rel] = artifact
                    self.artifact_repos[rel] = repository

    def _parse(self, path: Path, rel_override: str | None = None) -> Artifact | None:
        rel = rel_override or path.relative_to(self.root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.error(None, "SDD002", f"Cannot read UTF-8 artifact: {exc}", "Store the artifact as readable UTF-8.", path=rel)
            return None
        if "\r\n" in source:
            self.error(None, "SDD003", "Artifact uses CRLF line endings.", "Normalize it to UTF-8 with LF endings.", path=rel)
        lines = source.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            self.error(None, "SDD004", "Missing opening YAML frontmatter delimiter.", "Start the artifact with `---` YAML frontmatter.", path=rel)
            return None
        end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if end is None:
            self.error(None, "SDD005", "Missing closing YAML frontmatter delimiter.", "Close frontmatter with a standalone `---`.", path=rel)
            return None
        try:
            meta = yaml.safe_load("".join(lines[1:end]))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            self.error(None, "SDD006", f"Invalid YAML frontmatter: {exc}", "Correct the YAML syntax.", (mark.line + 2) if mark else 1, rel)
            return None
        if not isinstance(meta, dict):
            self.error(None, "SDD007", "Frontmatter is not a mapping.", "Use key/value YAML frontmatter.", path=rel)
            return None
        return Artifact(path, rel, meta, "".join(lines[end + 1 :]), source, end + 2)

    def _legacy_layouts(self) -> None:
        status_names = set().union(*STATUS.values(), TASK_STATUS)
        for dirname in ARTIFACT_DIRS:
            directory = self.root / dirname
            if not directory.is_dir():
                continue
            for child in directory.iterdir():
                if child.is_dir() and child.name.lower() in status_names:
                    rel = child.relative_to(self.root).as_posix()
                    self.error(None, "SDD008", f"Legacy status subfolder `{rel}` is invalid.", "Move artifacts to the type directory and keep lifecycle in frontmatter.", path=rel)

    def _common(self, artifact: Artifact) -> None:
        for field in COMMON_FIELDS:
            if artifact.meta.get(field) in (None, ""):
                self.error(artifact, "SDD010", f"Required field `{field}` is missing or empty.", f"Add a nonempty `{field}` value.")
        if artifact.kind not in STATUS:
            self.error(artifact, "SDD011", f"Unknown type `{artifact.kind or '<missing>'}`.", f"Use one of: {', '.join(sorted(STATUS))}.", artifact.line("type:"))
            return
        if artifact.status not in STATUS[artifact.kind]:
            self.error(artifact, "SDD012", f"Status `{artifact.status or '<missing>'}` is invalid for `{artifact.kind}`.", f"Use one of: {', '.join(sorted(STATUS[artifact.kind]))}.", artifact.line("status:"))
        for field in ("created", "updated"):
            value = artifact.meta.get(field)
            if not isinstance(value, dt.date) and not (isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
                self.error(artifact, "SDD013", f"`{field}` must be YYYY-MM-DD.", f"Set `{field}` to an ISO date.", artifact.line(f"{field}:"))
        if artifact.kind != "phase":
            for field in ("tags", "related"):
                if not isinstance(artifact.meta.get(field), list):
                    self.error(artifact, "SDD014", f"`{field}` must be a YAML list.", f"Use `{field}: []` when empty.", artifact.line(f"{field}:"))

    def sections(self, artifact: Artifact, level: int = 2) -> dict[str, tuple[int, str]]:
        lines = markdown_lines(artifact.body)
        matches: list[tuple[int, str]] = []
        pattern = re.compile(rf"^{'#' * level}\s+(.+?)\s*$")
        for index, (_, visible) in enumerate(lines):
            match = pattern.match(visible.rstrip("\r\n"))
            if match:
                matches.append((index, match.group(1).strip()))
        result: dict[str, tuple[int, str]] = {}
        for index, (start, heading) in enumerate(matches):
            end = matches[index + 1][0] if index + 1 < len(matches) else len(lines)
            line = artifact.body_line + start
            result[heading] = (line, "".join(raw for raw, _ in lines[start + 1 : end]))
        return result

    def _headings(self, artifact: Artifact) -> None:
        sections = self.sections(artifact)
        for heading in REQUIRED_HEADINGS.get(artifact.kind, ()):
            if heading not in sections:
                self.error(artifact, "SDD020", f"Required section `## {heading}` is missing.", f"Add a nonempty `## {heading}` section.")
        if artifact.kind in {"plan", "phase"}:
            heading = "Plan Completion Evidence" if artifact.kind == "plan" else "Phase Completion Evidence"
            if heading in sections:
                self._evidence(artifact, artifact.status, heading, *sections[heading])

    def _index(self) -> None:
        for artifact in self.artifacts:
            if artifact.kind == "spec":
                body = no_comments(artifact.body)
                families: dict[str, set[str]] = {}
                for family in ("FR", "NFR", "AC"):
                    found = DEFINITIONS[family].findall(body)
                    for value in duplicates(found):
                        self.error(artifact, "SDD030", f"Duplicate `{value}` in its owning spec.", "Assign a new append-only id and update citations.", artifact.line(value, True))
                    families[family] = set(found)
                self.spec_ids[artifact.rel] = families
            elif artifact.kind == "phase" and isinstance(artifact.meta.get("tasks"), list):
                plan_name = str(artifact.meta.get("plan", ""))
                for task in artifact.meta["tasks"]:
                    if not isinstance(task, dict) or not isinstance(task.get("id"), str):
                        continue
                    task_id = task["id"]
                    key = (plan_name, task_id)
                    if key in self.tasks:
                        self.error(artifact, "SDD031", f"Duplicate task id `{task_id}` in plan `{plan_name}`.", "Assign a unique append-only id within the plan and update references.")
                    else:
                        self.tasks[key] = (artifact, task)
            elif artifact.kind == "decision-log" and isinstance(artifact.meta.get("decisions"), list):
                for entry in artifact.meta["decisions"]:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        continue
                    decision_id = entry["id"]
                    repo_key = str(self.artifact_repos.get(artifact.rel, self.repo))
                    key = (repo_key, decision_id)
                    if key in self.decisions:
                        self.error(artifact, "SDD032", f"Duplicate decision id `{decision_id}`.", "Renumber the later entry and update all links.")
                    else:
                        self.decisions[key] = (artifact, entry)

    def resolve(self, reference: str) -> Artifact | None:
        value = reference.strip()
        path = Path(value)
        if not value or path.is_absolute() or "\\" in value or any(part in {".", ".."} for part in path.parts):
            return None
        for candidate in (value, f"{value}/README.md", f"{value}.md"):
            if candidate in self.by_path:
                return self.by_path[candidate]
        return None

    def _references(self, artifact: Artifact) -> None:
        related = artifact.meta.get("related", [])
        if not isinstance(related, list):
            return
        for reference in related:
            if not isinstance(reference, str) or not reference:
                self.error(artifact, "SDD040", "A `related` entry is not a nonempty string.", "Use a planning-root-relative artifact path.")
            elif self.resolve(reference) is None:
                self.error(artifact, "SDD041", f"Related path `{reference}` does not resolve.", "Point it at an existing artifact directory or Markdown file.", artifact.line(reference))

    def _specific(self, artifact: Artifact) -> None:
        self._open_questions(artifact)
        if artifact.kind == "spec":
            for family in ("FR", "NFR", "AC"):
                if not self.spec_ids[artifact.rel][family]:
                    self.error(artifact, "SDD050", f"Spec defines no `{family}-NN` element.", f"Number applicable elements with stable `{family}-NN` ids.")
        elif artifact.kind == "plan":
            self._plan(artifact)
        elif artifact.kind == "phase":
            self._phase(artifact)
        elif artifact.kind == "review":
            self._review(artifact)
        elif artifact.kind == "decision-log":
            self._ledger(artifact)
        elif artifact.kind == "debrief":
            self._required(artifact, ("plan", "phase", "phase_title"))

    def _required(self, artifact: Artifact, fields: Sequence[str]) -> None:
        for field in fields:
            if artifact.meta.get(field) in (None, ""):
                self.error(artifact, "SDD051", f"Required `{artifact.kind}` field `{field}` is missing.", f"Add a nonempty `{field}` value.")

    def _open_questions(self, artifact: Artifact) -> None:
        gated = (
            artifact.kind in {"spec", "design"} and artifact.status in {"approved", "implemented"}
        ) or (
            artifact.kind == "plan" and artifact.status in {"approved", "active", "complete"}
        )
        if not gated:
            return
        section = self.sections(artifact).get("Open Questions")
        if not section:
            return
        for question in open_question_items(section[1]):
            markers = list(NON_BLOCKING.finditer(question))
            marker = markers[0] if len(markers) == 1 else None
            prompt = question[: marker.start()].strip(" \t:—-") if marker else ""
            rationale = question[marker.end() :].strip(" \t:—-") if marker else ""
            if marker is None or not prompt or not rationale:
                self.error(
                    artifact,
                    "SDD153",
                    "Approved artifact contains a blocking or unexplained open question.",
                    "Resolve it or mark the bullet `**non-blocking** — <rationale>`.",
                    section[0],
                )

    def _append_only_repository_history(self) -> None:
        repository = git_root(self.root)
        if repository is None:
            return
        try:
            prefix = self.root.relative_to(repository).as_posix()
        except ValueError:
            return
        roots = [f"{prefix}/{name}" if prefix != "." else name for name in ("Specs", "Plans")]
        output, error = git_output(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", *roots)
        if error or output is None:
            return
        for raw_path in output.split(b"\0"):
            if not raw_path or not raw_path.endswith(b".md"):
                continue
            repository_relative = os.fsdecode(raw_path)
            baseline_bytes, baseline_error = git_output(repository, "show", f"HEAD:{repository_relative}")
            if baseline_error or baseline_bytes is None:
                continue
            try:
                baseline = baseline_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            meta = parse_frontmatter_source(baseline)
            kind = meta.get("type") if meta else None
            if kind not in {"spec", "plan", "phase"}:
                continue
            current_path = repository / repository_relative
            try:
                artifact_relative = current_path.relative_to(self.root).as_posix()
            except ValueError:
                artifact_relative = repository_relative
            worktree = read_utf8(current_path)
            index_bytes, index_error = git_output(repository, "show", f":{repository_relative}")
            index = None
            if not index_error and index_bytes is not None:
                try:
                    index = index_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    index = None
            for source_name, current in (("worktree", worktree), ("index", index)):
                self._check_retained_ids(kind, baseline, current, artifact_relative, source_name)

    def _check_retained_ids(self, kind: str, baseline: str, current: str | None, path: str, source_name: str) -> None:
        current_meta = parse_frontmatter_source(current or "")
        if not current_meta or current_meta.get("type") != kind:
            self.error(
                None,
                "SDD164",
                f"Previously tracked `{kind}` artifact changed type or disappeared from the {source_name}.",
                f"Restore the artifact as `type: {kind}` at its tracked path before moving or superseding it.",
                path=path,
            )
        if kind == "spec":
            prior = spec_definition_ids(baseline)
            retained = spec_retained_ids(current or "")
            code = "SDD154"
            noun = "spec"
            correction = "Restore the id and mark it retired with `removed — see <reason/citation>` or a struck-through definition."
        elif kind == "plan":
            prior = frontmatter_entry_ids(baseline, "phases")
            retained = frontmatter_entry_ids(current or "", "phases")
            code = "SDD155"
            noun = "phase"
            correction = "Restore the append-only phase id and preserve its historical entry."
        else:
            prior = frontmatter_entry_ids(baseline, "tasks")
            retained = frontmatter_entry_ids(current or "", "tasks")
            code = "SDD156"
            noun = "task"
            correction = "Restore the append-only task id and preserve its historical entry."
        for identifier in sorted(prior - retained):
            self.error(
                None,
                code,
                f"Previously tracked {noun} id `{identifier}` was removed from the {source_name}.",
                correction,
                path=path,
            )

    def _phase_ownership(self) -> None:
        owners: dict[str, list[str]] = {}
        for plan in (item for item in self.artifacts if item.kind == "plan"):
            plan_name = Path(plan.rel).parent.name
            phases = plan.meta.get("phases", [])
            if not isinstance(phases, list):
                continue
            for phase in phases:
                if not isinstance(phase, dict) or not isinstance(phase.get("doc"), str):
                    continue
                target = (Path(plan.rel).parent / phase["doc"]).as_posix()
                owners.setdefault(target, []).append(plan_name)
        for phase in (item for item in self.artifacts if item.kind == "phase"):
            parts = Path(phase.rel).parts
            physical_plan = parts[1] if len(parts) >= 3 and parts[0] == "Plans" else ""
            declared_plan = str(phase.meta.get("plan", ""))
            listed = owners.get(phase.rel, [])
            if len(listed) != 1 or listed[0] != physical_plan or declared_plan != physical_plan:
                self.error(
                    phase,
                    "SDD163",
                    f"Phase ownership is inconsistent: path plan `{physical_plan}`, declared plan `{declared_plan}`, listed by {listed}.",
                    "Place the phase under its owning plan, set the matching `plan` field, and list it exactly once in that plan README.",
                )

    def _plan(self, artifact: Artifact) -> None:
        phases = artifact.meta.get("phases")
        if not isinstance(phases, list):
            self.error(artifact, "SDD052", "`phases` must be a list.", "Use `phases: []` when empty.")
            return
        ids: list[str] = []
        for phase in phases:
            if not isinstance(phase, dict):
                self.error(artifact, "SDD053", "A phase entry is not a mapping.", "Add id, title, status, and doc fields.")
                continue
            for field in ("id", "title", "status", "doc"):
                if phase.get(field) in (None, ""):
                    self.error(artifact, "SDD054", f"Phase entry is missing `{field}`.", f"Add `{field}` to the entry.")
            phase_id = str(phase.get("id", ""))
            ids.append(phase_id)
            if phase.get("status") not in STATUS["phase"]:
                self.error(artifact, "SDD055", f"Phase `{phase_id}` has invalid status `{phase.get('status')}`.", "Use an allowed phase status.")
            doc = phase.get("doc")
            target = self.by_path.get((Path(artifact.rel).parent / str(doc)).as_posix()) if doc else None
            if target is None:
                self.error(artifact, "SDD056", f"Phase `{phase_id}` doc `{doc}` does not resolve.", "Point `doc` at an existing phase file.")
            else:
                plan_name = Path(artifact.rel).parent.name
                if target.kind != "phase":
                    self.error(artifact, "SDD150", f"Phase `{phase_id}` doc `{doc}` has type `{target.kind}`.", "Point `doc` at a `type: phase` artifact.")
                if str(target.meta.get("plan", "")) != plan_name:
                    self.error(artifact, "SDD151", f"Phase `{phase_id}` doc `{doc}` belongs to plan `{target.meta.get('plan')}`.", f"Set its `plan` field to `{plan_name}`.")
                if target.meta.get("title") != phase.get("title"):
                    self.error(artifact, "SDD152", f"Phase `{phase_id}` title disagrees with `{doc}`.", "Make the phase entry and document titles identical.")
                if str(target.meta.get("phase", "")) != phase_id:
                    self.error(artifact, "SDD057", f"Phase `{phase_id}` disagrees with `{doc}` id `{target.meta.get('phase')}`.", "Make both ids identical.")
                if target.status != phase.get("status"):
                    self.error(artifact, "SDD058", f"Phase `{phase_id}` status disagrees with `{doc}`.", "Make both statuses identical.")
                if artifact.status == "complete" and target.status != "complete":
                    self.error(artifact, "SDD059", f"Complete plan contains incomplete phase `{phase_id}`.", "Complete every phase first.")
        for value in duplicates(ids):
            self.error(artifact, "SDD060", f"Duplicate phase id `{value}`.", "Assign a unique append-only phase id.")
        if artifact.status == "complete":
            self._plan_rollup(artifact, phases)

    def _phase(self, artifact: Artifact) -> None:
        self._required(artifact, ("plan", "phase", "deliverable"))
        tasks = artifact.meta.get("tasks")
        if not isinstance(tasks, list):
            self.error(artifact, "SDD061", "`tasks` must be a list.", "Use `tasks: []` when empty.")
            return
        sections = self.sections(artifact)
        phase_id = str(artifact.meta.get("phase", ""))
        task_evidence: dict[str, str] = {}
        for task in tasks:
            if not isinstance(task, dict):
                self.error(artifact, "SDD062", "A task entry is not a mapping.", "Add id, title, status, and verification fields.")
                continue
            for field in ("id", "title", "status", "verification"):
                if task.get(field) in (None, ""):
                    self.error(artifact, "SDD063", f"Task is missing `{field}`.", f"Add a nonempty `{field}`.")
            task_id = str(task.get("id", ""))
            if not re.fullmatch(rf"{re.escape(phase_id)}\.\d+", task_id):
                self.error(artifact, "SDD064", f"Task id `{task_id}` is not in phase `{phase_id}`.", f"Use `{phase_id}.N`.")
            if task.get("status") not in TASK_STATUS:
                self.error(artifact, "SDD065", f"Task `{task_id}` has invalid status `{task.get('status')}`.", "Use an allowed task status.")
            heading = next((name for name in sections if re.match(rf"^{re.escape(task_id)}(?:\s*:|\s|$)", name)), None)
            if heading is None:
                self.error(artifact, "SDD066", f"Task `{task_id}` has no body section.", f"Add `## {task_id}: ...` with task detail sections.")
                continue
            line, body = sections[heading]
            for required in ("Subtasks", "Notes", "Completion Evidence"):
                if not re.search(rf"^###\s+{re.escape(required)}\s*$", body, re.MULTILINE):
                    self.error(artifact, "SDD067", f"Task `{task_id}` is missing `### {required}`.", f"Add it inside the task section.", line)
            evidence_blocks = heading_bodies(body, 3, "Completion Evidence")
            if len(evidence_blocks) > 1:
                self.error(artifact, "SDD067", f"Task `{task_id}` has duplicate visible `### Completion Evidence` sections.", "Keep exactly one Completion Evidence section inside the task.", line)
            if len(evidence_blocks) == 1:
                value = evidence_blocks[0]
                task_evidence[task_id] = no_comments(value).strip()
                self._evidence(artifact, str(task.get("status", "")), f"Task {task_id} Completion Evidence", line, value)
            if artifact.status == "complete" and task.get("status") != "complete":
                self.error(artifact, "SDD068", f"Complete phase contains incomplete task `{task_id}`.", "Complete every task first.")
        criteria = sections.get("Acceptance Criteria")
        if artifact.status == "complete" and criteria and re.search(r"^-\s*\[\s\]", criteria[1], re.MULTILINE):
            self.error(artifact, "SDD069", "Complete phase has unchecked acceptance criteria.", "Verify and check every criterion.", criteria[0])
        if artifact.status == "complete":
            phase_evidence = sections.get("Phase Completion Evidence")
            if phase_evidence:
                rollup = phase_evidence[1]
                for task in tasks:
                    if not isinstance(task, dict) or task.get("status") != "complete":
                        continue
                    task_id = str(task.get("id", ""))
                    evidence = task_evidence.get(task_id, "").strip()
                    copied = rollup_bodies(rollup, f"Task {task_id} Evidence Rollup")
                    if not evidence or len(copied) != 1 or copied[0].strip() != evidence:
                        self.error(
                            artifact,
                            "SDD157",
                            f"Phase completion evidence does not contain the verbatim evidence rollup for task `{task_id}`.",
                            f"Add `### Task {task_id} Evidence Rollup` and repeat its populated Completion Evidence body verbatim.",
                            phase_evidence[0],
                        )

    def _plan_rollup(self, artifact: Artifact, phases: list[Any]) -> None:
        plan_evidence = self.sections(artifact).get("Plan Completion Evidence")
        if not plan_evidence:
            return
        rollup = plan_evidence[1]
        for phase in phases:
            if not isinstance(phase, dict) or not isinstance(phase.get("doc"), str):
                continue
            phase_id = str(phase.get("id", ""))
            target = self.by_path.get((Path(artifact.rel).parent / phase["doc"]).as_posix())
            if not target:
                continue
            missing: list[str] = []
            sections = self.sections(target)
            phase_body = sections.get("Phase Completion Evidence", (1, ""))[1]
            phase_rollups = rollup_bodies(rollup, f"Phase {phase_id} Evidence Rollup")
            if len(phase_rollups) != 1:
                missing.append(f"phase {phase_id} rollup")
            elif evidence_rows(phase_rollups[0]) != evidence_rows(phase_body):
                missing.append(f"phase {phase_id} evidence rows")
            tasks = target.meta.get("tasks", [])
            if isinstance(tasks, list):
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    task_id = str(task.get("id", ""))
                    heading = next((name for name in sections if re.match(rf"^{re.escape(task_id)}(?:\s*:|\s|$)", name)), None)
                    task_body = sections[heading][1] if heading else ""
                    evidence = completion_evidence_body(task_body)
                    task_rollups = rollup_bodies(rollup, f"Task {task_id} Evidence Rollup")
                    if len(task_rollups) != 1:
                        missing.append(f"task {task_id} rollup")
                    elif evidence_rows(task_rollups[0]) != evidence_rows(evidence or ""):
                        missing.append(f"task {task_id} evidence rows")
            if missing:
                self.error(
                    artifact,
                    "SDD158",
                    f"Plan completion evidence omits {', '.join(sorted(set(missing)))}.",
                    "Add labeled phase/task Evidence Rollup blocks and repeat each child's exact command/tool evidence rows.",
                    plan_evidence[0],
                )

    def _evidence(self, artifact: Artifact, status: str, name: str, line: int, body: str) -> None:
        pending = PENDING in body
        if status == "complete" and pending:
            self.error(artifact, "SDD070", f"Complete `{name}` is pending.", "Replace the marker with retrospective evidence.", line)
            return
        if pending:
            return
        labels = ("Verified", "Repository", "VCS", "Revision / base", "Identity recheck")
        for label in labels:
            if not re.search(rf"^\s*-\s+{re.escape(label)}:\s*\S", body, re.MULTILINE):
                self.error(artifact, "SDD071", f"`{name}` lacks `{label}`.", f"Add populated `{label}` evidence.", line)
        verified = markdown_scalar(evidence_value(body, "Verified"))
        if verified and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified):
            self.error(artifact, "SDD072", f"`{name}` has invalid verification date `{verified}`.", "Use YYYY-MM-DD.", line)
        vcs = markdown_scalar(evidence_value(body, "VCS")) or ""
        if vcs and vcs not in {"git", "git-worktree", "perforce", "none"}:
            self.error(artifact, "SDD072", f"`{name}` has invalid VCS `{vcs}`.", "Use git, git-worktree, perforce, or none.", line)
        revision = markdown_scalar(evidence_value(body, "Revision / base")) or ""
        if vcs in {"git", "git-worktree"} and revision and not re.fullmatch(r"[0-9a-fA-F]{40}(?:-dirty)?", revision):
            self.error(artifact, "SDD072", f"`{name}` has invalid Git revision/base `{revision}`.", "Record the full 40-digit revision, optionally followed by `-dirty`.", line)
        if vcs == "none" and revision and revision != "none":
            self.error(artifact, "SDD072", f"`{name}` with VCS `none` has revision/base `{revision}`.", "Use `none`.", line)
        repository = markdown_scalar(evidence_value(body, "Repository"))
        expected_repository = self._repo_for_artifact(artifact)
        if repository:
            recorded_repository = Path(repository).expanduser().resolve()
            if recorded_repository != expected_repository:
                self.error(artifact, "SDD072", f"`{name}` repository `{recorded_repository}` does not match target `{expected_repository}`.", "Record the exact resolved target repository root.", line)
        fallback = revision.endswith("-dirty") or vcs in {"perforce", "none"}
        fallback_labels = ("Fallback reason", "Evidence exclusions", "Governing intent", "Ignored inputs", "Directory inputs", "Content snapshot")
        if fallback:
            for label in fallback_labels:
                if not re.search(rf"^\s*-\s+{re.escape(label)}:\s*\S", body, re.MULTILINE):
                    self.error(artifact, "SDD071", f"`{name}` fallback identity lacks `{label}`.", f"Add populated `{label}` fallback evidence.", line)
        exclusions = parse_exclusions(evidence_value(body, "Evidence exclusions")) if fallback else set()
        ignored_inputs: set[str] = set()
        directory_inputs: set[str] = set()
        if fallback:
            ignored_inputs, ignored_error = parse_inventory_paths(evidence_value(body, "Ignored inputs"))
            directory_inputs, directory_error = parse_inventory_paths(evidence_value(body, "Directory inputs"))
            for label, inventory_error in (("Ignored inputs", ignored_error), ("Directory inputs", directory_error)):
                if inventory_error:
                    self.error(artifact, "SDD165", f"`{name}` has malformed `{label}`: {inventory_error}", "Use `none with <inspection basis>` or `paths: <comma-separated paths>; <digests/basis>`.", line)
        governing = evidence_value(body, "Governing intent")
        snapshot = evidence_value(body, "Content snapshot")
        if not fallback and any(evidence_value(body, label) for label in fallback_labels):
            self.error(artifact, "SDD074", f"`{name}` uses fallback capture fields for a clean Git implementation commit.", "Remove snapshot/projection/exclusion fields; the tested commit is the durable source identity.", line)
        capture_paths = [location for value in (governing, snapshot) if value and (location := digest_location(value)) and not urlparse(location).scheme]
        if fallback:
            self._check_exclusions(artifact, exclusions, capture_paths, name, line)
        recorded_inputs = parse_recorded_inputs(governing) if governing else set()
        required_inputs = self._required_intent_inputs(artifact) if fallback else set()
        if fallback and governing and recorded_inputs != required_inputs:
            self.error(artifact, "SDD076", f"`{name}` governing inputs {sorted(recorded_inputs)} do not match required inputs {sorted(required_inputs)}.", "Regenerate the projection from the plan, governing phase(s), related specs/designs, and cited accepted decisions.", line)
        if vcs in {"git", "git-worktree"} and revision and not revision.endswith("-dirty"):
            compare_current = self.identity_mode != "historical"
            self._verify_clean_git_identity(artifact, revision, name, line, compare_current)
        if status == "complete":
            self._verify_evidence_committed(artifact, name, body, line)
        rows = evidence_rows(body)
        if not rows:
            self.error(artifact, "SDD072", f"`{name}` has no conforming command or tool evidence row.", "Add a four-column command or tool row with PASS and specific observable evidence.", line)
        else:
            for row_kind, row in rows:
                if not row[2].startswith("PASS"):
                    self.error(artifact, "SDD072", f"`{name}` contains non-passing result `{row[2]}`.", "Every required command and inspection row must record PASS.", line)
                if row_kind == "command" and not re.search(r"\bexit\s+0\b", row[2], re.IGNORECASE):
                    self.error(artifact, "SDD072", f"`{name}` command row lacks explicit `exit 0`.", "Record PASS with the command exit status.", line)
        if re.search(r"\b(?:FAIL|FAILED|exit\s+[1-9]\d*)\b", body, re.IGNORECASE):
            self.error(artifact, "SDD073", f"`{name}` contains failing evidence.", "Return it to a non-complete status until final checks pass.", line)
        if governing:
            self._digest(
                artifact,
                name,
                governing,
                line,
                require_inputs=True,
                capture_kind="intent",
                expected_inputs=recorded_inputs,
            )
        if fallback:
            if snapshot:
                self._digest(
                    artifact,
                    name,
                    snapshot,
                    line,
                    capture_kind="snapshot",
                    expected_vcs=vcs,
                    expected_revision=revision,
                    expected_exclusions=exclusions,
                    expected_ignored=ignored_inputs,
                    expected_directories=directory_inputs,
                )
            else:
                self.error(artifact, "SDD074", f"`{name}` requires a content snapshot.", "Record its SHA-256 and durable manifest path.", line)
            if status == "complete":
                for capture in capture_paths:
                    self._verify_capture_committed(artifact, capture, name, line)
        recheck = evidence_value(body, "Identity recheck") or ""
        if recheck and (
            not re.search(r"\bmatch(?:ed|es|ing)?\b", recheck, re.IGNORECASE)
            or not re.search(r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d", recheck)
        ):
            self.error(artifact, "SDD075", f"`{name}` recheck lacks a timestamped matching result.", "Record the exact tool, ISO timestamp, and matching identity.", line)
        if vcs in {"git", "git-worktree"} and revision and not revision.endswith("-dirty") and revision.lower() not in recheck.lower():
            self.error(artifact, "SDD075", f"`{name}` recheck does not name implementation revision `{revision}`.", "Record the exact tested commit in the identity-recheck procedure and result.", line)

    def _verify_clean_git_identity(self, artifact: Artifact, revision: str, name: str, line: int, compare_current: bool) -> None:
        repository = self._repo_for_artifact(artifact)

        def git(*args: str) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(["git", "-C", str(repository), *args], check=False, capture_output=True)

        inside = git("rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip() != b"true":
            self.error(artifact, "SDD072", f"`{name}` records Git but `{repository}` is not a Git worktree.", "Correct the repository/VCS evidence.", line)
            return
        commit = git("cat-file", "-e", f"{revision}^{{commit}}")
        if commit.returncode != 0:
            self.error(artifact, "SDD072", f"`{name}` Git revision `{revision}` does not exist in `{repository}`.", "Record an existing full commit revision.", line)
            return
        if not compare_current:
            return
        ancestor = git("merge-base", "--is-ancestor", revision, "HEAD")
        if ancestor.returncode != 0:
            self.error(artifact, "SDD072", f"`{name}` implementation revision `{revision}` is not an ancestor of current HEAD.", "Check out a descendant containing the completed feature or use historical identity mode for an archival audit.", line)

    def _verify_evidence_committed(self, artifact: Artifact, name: str, body: str, line: int) -> None:
        repository = git_root(artifact.path)
        if repository is None:
            self.error(artifact, "SDD072", f"`{name}` is complete but its planning artifact is not in a Git worktree.", "Commit the lifecycle/evidence artifact in its planning repository before finalizing completion.", line)
            return
        try:
            relative = artifact.path.resolve().relative_to(repository).as_posix()
        except ValueError:
            self.error(artifact, "SDD072", f"`{name}` planning artifact cannot be resolved inside its Git worktree.", "Commit the lifecycle/evidence artifact before finalizing completion.", line)
            return
        tracked = subprocess.run(
            ["git", "-C", str(repository), "show", f"HEAD:{relative}"],
            check=False,
            capture_output=True,
        )
        if tracked.returncode != 0:
            self.error(artifact, "SDD072", f"`{name}` completion evidence is not committed at HEAD.", "Create the separate scoped lifecycle/evidence commit before finalizing completion.", line)
            return
        committed_source = tracked.stdout.decode("utf-8", errors="replace")
        committed_meta = parse_frontmatter_source(committed_source)
        source_lines = committed_source.splitlines(keepends=True)
        frontmatter_end = next(
            (index for index, value in enumerate(source_lines[1:], 1) if value.strip() == "---"),
            None,
        )
        if committed_meta is None or frontmatter_end is None:
            self.error(artifact, "SDD072", f"`{name}` committed planning artifact is malformed.", "Commit a valid populated lifecycle artifact before finalizing completion.", line)
            return
        committed = Artifact(
            artifact.path,
            artifact.rel,
            committed_meta,
            "".join(source_lines[frontmatter_end + 1 :]),
            committed_source,
            frontmatter_end + 2,
        )
        committed_body: str | None = None
        lifecycle_complete = False
        task_match = re.fullmatch(r"Task\s+(\S+)\s+Completion Evidence", name)
        if task_match:
            task_id = task_match.group(1)
            tasks = committed.meta.get("tasks", [])
            lifecycle_complete = any(
                isinstance(task, dict)
                and str(task.get("id", "")) == task_id
                and task.get("status") == "complete"
                for task in tasks
            ) if isinstance(tasks, list) else False
            sections = self.sections(committed)
            heading = next(
                (value for value in sections if re.match(rf"^{re.escape(task_id)}(?:\s*:|\s|$)", value)),
                None,
            )
            if heading:
                committed_body = completion_evidence_body(sections[heading][1])
                subtasks = heading_bodies(sections[heading][1], 3, "Subtasks")
                lifecycle_complete = lifecycle_complete and bool(subtasks) and not re.search(
                    r"^-\s*\[\s\]", subtasks[0], re.MULTILINE
                )
        elif name == "Phase Completion Evidence":
            lifecycle_complete = committed.status == "complete"
            committed_body = next(iter(heading_bodies(committed.body, 2, name)), None)
            criteria = heading_bodies(committed.body, 2, "Acceptance Criteria")
            lifecycle_complete = lifecycle_complete and bool(criteria) and not re.search(
                r"^-\s*\[\s\]", criteria[0], re.MULTILINE
            )
            plan_name = self._plan_name(artifact)
            plan_path = self.root / "Plans" / plan_name / "README.md" if plan_name else None
            plan_repository = git_root(plan_path) if plan_path else None
            if plan_path is None or plan_repository != repository:
                lifecycle_complete = False
            else:
                plan_relative = plan_path.resolve().relative_to(plan_repository).as_posix()
                plan_at_head = subprocess.run(
                    ["git", "-C", str(plan_repository), "show", f"HEAD:{plan_relative}"],
                    check=False,
                    capture_output=True,
                )
                plan_meta = parse_frontmatter_source(
                    plan_at_head.stdout.decode("utf-8", errors="replace")
                ) if plan_at_head.returncode == 0 else None
                phases = plan_meta.get("phases", []) if plan_meta else []
                lifecycle_complete = lifecycle_complete and any(
                    isinstance(phase, dict)
                    and str(phase.get("id", "")) == str(artifact.meta.get("phase", ""))
                    and phase.get("status") == "complete"
                    for phase in phases
                ) if isinstance(phases, list) else False
        elif name == "Plan Completion Evidence":
            lifecycle_complete = committed.status == "complete"
            committed_body = next(iter(heading_bodies(committed.body, 2, name)), None)
        if not lifecycle_complete or committed_body is None:
            self.error(artifact, "SDD072", f"`{name}` lifecycle completion is not committed at HEAD.", "Commit the complete status, checked criteria/subtasks, and evidence in the scoped lifecycle commit.", line)
            return
        if no_comments(body).strip() != no_comments(committed_body).strip():
            self.error(artifact, "SDD072", f"`{name}` completion evidence differs from its committed section.", "Commit the populated evidence and lifecycle status in a scoped bookkeeping commit.", line)

    def _verify_capture_committed(self, artifact: Artifact, capture: str, name: str, line: int) -> None:
        target = self._capture_path(artifact, capture)
        repository = git_root(target)
        planning_repository = git_root(artifact.path)
        if repository is None or repository != planning_repository:
            self.error(artifact, "SDD078", f"`{name}` local fallback capture `{capture}` is not in the lifecycle artifact's Git worktree.", "Commit local fallback objects in the same planning repository as the lifecycle evidence or use a validated immutable artifact URI with retention.", line)
            return
        if not target.is_file():
            self.error(artifact, "SDD078", f"`{name}` local fallback capture `{capture}` is missing from the worktree.", "Restore the exact committed fallback object or correct the evidence path.", line)
            return
        paths = [target]
        contents = Path(f"{target}.contents")
        if contents.is_dir():
            paths.extend(item for item in contents.iterdir() if item.is_file())
        for path in paths:
            try:
                relative = path.resolve().relative_to(repository).as_posix()
            except ValueError:
                self.error(artifact, "SDD078", f"`{name}` fallback object `{path}` is outside its Git worktree.", "Store and commit fallback objects under the planning root.", line)
                continue
            committed = subprocess.run(
                ["git", "-C", str(repository), "show", f"HEAD:{relative}"],
                check=False,
                capture_output=True,
            )
            if committed.returncode != 0 or committed.stdout != path.read_bytes():
                self.error(artifact, "SDD078", f"`{name}` fallback object `{relative}` is not durably committed at HEAD.", "Commit the exact fallback manifest/content object with the lifecycle evidence or use an immutable retained URI.", line)

    def _check_exclusions(self, artifact: Artifact, exclusions: set[str], capture_paths: list[str], name: str, line: int) -> None:
        if not exclusions:
            return
        repository = self._repo_for_artifact(artifact)
        allowed: set[str] = set(capture_paths)
        try:
            allowed.add(artifact.path.resolve().relative_to(repository).as_posix())
        except ValueError:
            pass
        plan_names = self._candidate_plan_names(artifact)
        for plan_name in plan_names:
            plan_readme = self.root / "Plans" / plan_name / "README.md"
            if plan_readme.is_file():
                try:
                    allowed.add(plan_readme.resolve().relative_to(repository).as_posix())
                except ValueError:
                    pass
            notes = self.root / "Plans" / plan_name / "notes"
            if notes.is_dir():
                for debrief in notes.glob("*.md"):
                    try:
                        allowed.add(debrief.resolve().relative_to(repository).as_posix())
                    except ValueError:
                        pass
        for capture in capture_paths:
            contents = Path(f"{self._capture_path(artifact, capture)}.contents")
            if contents.is_dir():
                for item in contents.iterdir():
                    if item.is_file():
                        allowed.add(item.resolve().relative_to(repository).as_posix())
        forbidden = sorted(exclusions - allowed)
        if forbidden:
            self.error(artifact, "SDD076", f"`{name}` excludes non-evidence paths: {', '.join(forbidden)}.", "Exclude only the governing phase/plan/debrief and recorded canonical evidence objects.", line)

    def _required_intent_inputs(self, artifact: Artifact) -> set[str]:
        required: dict[str, Artifact] = {artifact.rel: artifact}
        plan_name = self._plan_name(artifact)
        plan = self.by_path.get(f"Plans/{plan_name}/README.md") if plan_name else None
        if artifact.kind == "plan":
            plan = artifact
        if plan:
            required[plan.rel] = plan
            phases = plan.meta.get("phases", [])
            if artifact.kind == "plan" and isinstance(phases, list):
                for phase in phases:
                    if isinstance(phase, dict) and isinstance(phase.get("doc"), str):
                        target = self.by_path.get((Path(plan.rel).parent / phase["doc"]).as_posix())
                        if target:
                            required[target.rel] = target
            related = plan.meta.get("related", [])
            if isinstance(related, list):
                for reference in related:
                    target = self.resolve(reference) if isinstance(reference, str) else None
                    if target and target.kind in {"spec", "design"}:
                        required[target.rel] = target
        repository_key = str(self._repo_for_artifact(artifact))
        combined = "\n".join(item.source for item in required.values())
        for number in IDS["D"].findall(no_comments(combined)):
            decision_id = f"D-{number}"
            decision = self.decisions.get((repository_key, decision_id))
            if decision and decision[1].get("status") == "accepted":
                required[decision_id] = decision[0]
        return set(required)

    def _digest(
        self,
        artifact: Artifact,
        name: str,
        value: str,
        line: int,
        require_inputs: bool = False,
        capture_kind: str = "",
        expected_inputs: set[str] | None = None,
        expected_vcs: str = "",
        expected_revision: str = "",
        expected_exclusions: set[str] | None = None,
        expected_ignored: set[str] | None = None,
        expected_directories: set[str] | None = None,
    ) -> None:
        digest = SHA256.search(value)
        relative = digest_location(value)
        if digest is None or relative is None or (require_inputs and "inputs:" not in value):
            self.error(artifact, "SDD076", f"`{name}` contains malformed digest evidence.", "Record SHA-256, durable path, and required inputs.", line)
            return
        parsed = urlparse(relative)
        if parsed.scheme:
            if parsed.scheme != "ipfs" or ipfs_sha256(relative) != digest.group(1).lower() or "retention:" not in value.lower():
                self.error(artifact, "SDD077", f"Evidence URI `{relative}` is not demonstrably content-addressed and retained.", "Use a supported immutable URI containing the recorded SHA-256 and record retention.", line)
            return
        target = self._capture_path(artifact, relative)
        try:
            target.relative_to(self.root)
        except ValueError:
            self.error(artifact, "SDD077", f"Evidence path `{relative}` is outside the planning root.", "Store evidence under the planning root.", line)
            return
        if not target.is_file():
            self.error(artifact, "SDD078", f"Evidence file `{relative}` does not exist.", "Create it or correct the path.", line)
            return
        content = target.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual.lower() != digest.group(1).lower():
            self.error(artifact, "SDD079", f"Evidence file `{relative}` hashes to `{actual}`, not the recorded digest.", "Regenerate or correct the evidence.", line)
            return
        if capture_kind == "intent":
            error, projection_inputs, records = validate_intent_projection(content)
            if error:
                self.error(artifact, "SDD079", f"Governing-intent file `{relative}` is malformed: {error}", "Regenerate the canonical `sdd-intent-v2` projection.", line)
            elif expected_inputs is not None and projection_inputs != expected_inputs:
                self.error(artifact, "SDD079", f"Governing-intent inputs {sorted(projection_inputs)} do not match recorded inputs {sorted(expected_inputs)}.", "Record the exact projection input references.", line)
            elif self.identity_mode != "historical":
                for kind, reference, payload in records:
                    expected = self._current_projection(artifact, kind, reference)
                    if expected is None:
                        self.error(artifact, "SDD079", f"Governing-intent input `{reference}` does not resolve for current projection.", "Correct the input reference or use explicit historical mode for a historical audit.", line)
                    elif payload != expected:
                        self.error(artifact, "SDD079", f"Governing-intent payload for `{reference}` does not match the current canonical projection.", "Regenerate the governing-intent projection immediately before completion.", line)
        elif capture_kind == "snapshot":
            for error in validate_snapshot(target, content, expected_vcs, expected_revision, expected_exclusions or set()):
                self.error(artifact, "SDD079", f"Snapshot `{relative}` is malformed: {error}", "Regenerate the canonical snapshot manifest and content objects.", line)
            if (
                self.identity_mode != "historical"
                and expected_vcs in {"git", "git-worktree"}
                and expected_revision.endswith("-dirty")
            ):
                for error in compare_dirty_git_snapshot(
                    target,
                    content,
                    self._repo_for_artifact(artifact),
                    expected_revision.removesuffix("-dirty"),
                    expected_exclusions or set(),
                    expected_ignored or set(),
                    expected_directories or set(),
                ):
                    self.error(
                        artifact,
                        "SDD159",
                        f"Snapshot `{relative}` does not match the current Git worktree: {error}",
                        "Regenerate the canonical dirty snapshot after final verification.",
                        line,
                    )

    def _current_projection(self, governing: Artifact, kind: str, reference: str) -> bytes | None:
        if kind == "artifact":
            target = self.resolve(reference)
            return project_artifact(target) if target else None
        repository_key = str(self._repo_for_artifact(governing))
        decision_id = reference.rsplit("#", 1)[-1]
        entry = self.decisions.get((repository_key, decision_id))
        return project_decision_entry(entry[0], decision_id) if entry else None

    def _review(self, artifact: Artifact) -> None:
        self._required(artifact, ("review_of", "rev"))
        if isinstance(artifact.meta.get("review_of"), str) and self.resolve(artifact.meta["review_of"]) is None:
            self.error(artifact, "SDD080", f"`review_of` `{artifact.meta['review_of']}` does not resolve.", "Point it at the reviewed artifact.")
        findings = artifact.meta.get("findings")
        followups = artifact.meta.get("followups")
        if not isinstance(findings, list):
            self.error(artifact, "SDD081", "`findings` must be a list.", "Use `findings: []` when empty.")
            return
        if not isinstance(followups, list):
            self.error(artifact, "SDD082", "`followups` must be a list.", "Use `followups: []` when empty.")
            followups = []
        statuses: dict[str, str] = {}
        resolution = self.sections(artifact).get("Resolution Log", (1, ""))[1]
        finding_ids: list[str] = []
        for finding in findings:
            if not isinstance(finding, dict):
                self.error(artifact, "SDD083", "A finding is not a mapping.", "Add id, severity, title, and status.")
                continue
            finding_id = str(finding.get("id", ""))
            finding_ids.append(finding_id)
            statuses[finding_id] = str(finding.get("status", ""))
            for field in ("id", "severity", "title", "status"):
                if finding.get(field) in (None, ""):
                    self.error(artifact, "SDD083", f"Finding is missing `{field}`.", f"Add a nonempty `{field}`.")
            if not re.fullmatch(r"F-\d{2,}", finding_id):
                self.error(artifact, "SDD084", f"Invalid finding id `{finding_id}`.", "Use `F-NN`.")
            if finding.get("severity") not in {"critical", "major", "minor", "question"}:
                self.error(artifact, "SDD085", f"Finding `{finding_id}` has invalid severity.", "Use critical, major, minor, or question.")
            status = finding.get("status")
            if status not in FINDING_STATUS:
                self.error(artifact, "SDD086", f"Finding `{finding_id}` has invalid status `{status}`.", "Use an allowed finding status.")
            if not re.search(rf"^###\s+{re.escape(finding_id)}\b", artifact.body, re.MULTILINE):
                self.error(artifact, "SDD087", f"Finding `{finding_id}` has no body section.", f"Add `### {finding_id} — ...`.")
            if status != "open":
                entry = re.search(rf"^###\s+{re.escape(finding_id)}\s+—\s+([a-z-]+)\b", resolution, re.MULTILINE)
                if not entry:
                    self.error(artifact, "SDD088", f"Terminal finding `{finding_id}` has no resolution entry.", "Append a dated Resolution Log entry.")
                elif entry.group(1) != status:
                    self.error(artifact, "SDD089", f"Finding `{finding_id}` status disagrees with its resolution.", "Make both dispositions agree.")
        for value in duplicates(finding_ids):
            self.error(artifact, "SDD090", f"Duplicate finding id `{value}`.", "Assign a new append-only id.")
        has_open = any(value == "open" for value in statuses.values())
        if artifact.status == "resolved" and has_open:
            self.error(artifact, "SDD091", "Resolved review contains open findings.", "Resolve them or set review status to open.")
        tracked_findings: set[str] = set()
        followup_ids: list[str] = []
        plan_names = self._candidate_plan_names(artifact)
        for followup in followups:
            if not isinstance(followup, dict):
                self.error(artifact, "SDD092", "A follow-up is not a mapping.", "Add id, finding, summary, and tracked_in.")
                continue
            followup_id = str(followup.get("id", ""))
            finding_id = str(followup.get("finding", ""))
            followup_ids.append(followup_id)
            for field in ("id", "finding", "summary", "tracked_in"):
                if field not in followup:
                    self.error(artifact, "SDD092", f"Follow-up is missing `{field}`.", f"Add the `{field}` field.")
            if not re.fullmatch(r"FU-\d{2,}", followup_id):
                self.error(artifact, "SDD093", f"Invalid follow-up id `{followup_id}`.", "Use `FU-NN`.")
            if finding_id not in statuses:
                self.error(artifact, "SDD094", f"Follow-up `{followup_id}` references unknown `{finding_id}`.", "Reference a finding in this review.")
            tracked = followup.get("tracked_in")
            if not tracked:
                self.error(artifact, "SDD095", f"Follow-up `{followup_id}` is floating.", "Create a plan task and set `tracked_in`.")
            else:
                matches = [plan for plan in plan_names if (plan, str(tracked)) in self.tasks]
                if not matches:
                    self.error(artifact, "SDD096", f"Follow-up `{followup_id}` points to unknown task `{tracked}`.", "Reference an existing task in a related plan.")
                elif len(matches) > 1:
                    self.error(artifact, "SDD096", f"Follow-up `{followup_id}` task `{tracked}` is ambiguous across plans {matches}.", "Link the review to one plan or use an unambiguous tracked task.")
                else:
                    tracked_findings.add(finding_id)
        for value in duplicates(followup_ids):
            self.error(artifact, "SDD097", f"Duplicate follow-up id `{value}`.", "Assign a new append-only id.")
        for finding_id, status in statuses.items():
            if status != "deferred" or finding_id in tracked_findings:
                continue
            entry = resolution_entry(resolution, finding_id)
            cited = set(re.findall(r"\b\d+\.\d+\b", entry))
            if not any((plan_name, task_id) in self.tasks for plan_name in plan_names for task_id in cited):
                self.error(artifact, "SDD098", f"Deferred finding `{finding_id}` is untracked.", "Cite an existing task in the reviewed plan or add a tracked follow-up.")
        self._review_supersession(artifact)

    def _review_supersession(self, artifact: Artifact) -> None:
        if artifact.status == "superseded" and not artifact.meta.get("superseded_by"):
            self.error(artifact, "SDD099", "Superseded review lacks `superseded_by`.", "Link the replacing review.")
        if artifact.meta.get("superseded_by") and artifact.status != "superseded":
            self.error(artifact, "SDD099", f"Review with `superseded_by` has status `{artifact.status}`.", "Set its artifact status to `superseded`.")
        for field, reverse in (("supersedes", "superseded_by"), ("superseded_by", "supersedes")):
            value = artifact.meta.get(field)
            if not value:
                continue
            target = self.resolve(str(value))
            if target is None or target.kind != "review":
                self.error(artifact, "SDD100", f"Review `{field}` `{value}` does not resolve.", "Point it at an existing review.")
            elif target.meta.get(reverse) not in {artifact.rel, artifact.rel.removesuffix(".md")}:
                self.error(artifact, "SDD101", f"Review `{field}` link is not reciprocated.", f"Add matching `{reverse}`.")
            elif normalized(target.meta.get("review_of")) != normalized(artifact.meta.get("review_of")):
                self.error(artifact, "SDD102", f"Review `{field}` links reviews of different targets.", "Link only reviews of the same normalized `review_of` target.")
            elif field == "supersedes" and target.status != "superseded":
                self.error(artifact, "SDD102", f"Superseded review `{value}` still has status `{target.status}`.", "Set the replaced review status to `superseded`.")

    def _plan_name(self, artifact: Artifact) -> str | None:
        if artifact.kind == "phase" and artifact.meta.get("plan"):
            return str(artifact.meta["plan"])
        parts = Path(artifact.rel).parts
        if len(parts) >= 2 and parts[0] == "Plans":
            return parts[1]
        review_of = artifact.meta.get("review_of")
        if isinstance(review_of, str):
            review_parts = Path(review_of).parts
            if len(review_parts) >= 2 and review_parts[0] == "Plans":
                return review_parts[1]
        return None

    def _candidate_plan_names(self, artifact: Artifact) -> set[str]:
        direct = self._plan_name(artifact)
        if direct:
            return {direct}
        targets: list[Artifact] = []
        review_of = artifact.meta.get("review_of")
        if isinstance(review_of, str):
            target = self.resolve(review_of)
            if target:
                targets.append(target)
        related = artifact.meta.get("related", [])
        if isinstance(related, list):
            for reference in related:
                target = self.resolve(reference) if isinstance(reference, str) else None
                if target:
                    targets.append(target)
        result: set[str] = set()
        for plan in (item for item in self.artifacts if item.kind == "plan"):
            plan_name = self._plan_name(plan)
            if plan_name and any(
                plan.rel == target.rel
                or self._artifacts_connected(plan, target)
                or self._artifacts_connected(target, plan)
                for target in targets
            ):
                result.add(plan_name)
        return result

    def _ledger(self, artifact: Artifact) -> None:
        entries = artifact.meta.get("decisions")
        if not isinstance(entries, list):
            self.error(artifact, "SDD110", "`decisions` must be a list.", "Use `decisions: []` when empty.")
            return
        for entry in entries:
            if not isinstance(entry, dict):
                self.error(artifact, "SDD111", "A decision is not a mapping.", "Use the decision entry schema.")
                continue
            for field in ("id", "kind", "status", "date", "decided_by", "statement", "rationale"):
                if entry.get(field) in (None, ""):
                    self.error(artifact, "SDD112", f"Decision is missing `{field}`.", f"Add a nonempty `{field}`.")
            decision_id = str(entry.get("id", ""))
            if not re.fullmatch(r"D-\d{4,}", decision_id):
                self.error(artifact, "SDD113", f"Invalid decision id `{decision_id}`.", "Use `D-NNNN`.")
            if entry.get("kind") not in {"decision", "definition", "answered-question", "assumption"}:
                self.error(artifact, "SDD114", f"Decision `{decision_id}` has invalid kind.", "Use an allowed decision kind.")
            if entry.get("status") not in DECISION_STATUS:
                self.error(artifact, "SDD115", f"Decision `{decision_id}` has invalid status.", "Use an allowed decision status.")
            if entry.get("kind") == "answered-question" and not entry.get("question"):
                self.error(artifact, "SDD116", f"Answered question `{decision_id}` lacks `question`.", "Record the question.")
            if entry.get("decided_by") not in {"agent", "user", "user-approved"}:
                self.error(artifact, "SDD117", f"Decision `{decision_id}` has invalid `decided_by`.", "Use agent, user, or user-approved as allowed by lifecycle status.")
            if entry.get("decided_by") == "agent" and entry.get("status") != "proposed":
                self.error(artifact, "SDD118", f"Decision `{decision_id}` attributes a non-proposed entry to agent.", "Use agent only for unconfirmed proposals; user acceptance changes provenance to user-approved.")

    def _citations(self, artifact: Artifact) -> None:
        body = no_comments(artifact.body)
        if artifact.kind != "decision-log":
            repository_key = str(self._repo_for_artifact(artifact))
            for number in IDS["D"].findall(body):
                decision_id = f"D-{number}"
                target = self.decisions.get((repository_key, decision_id))
                if target is None:
                    self.error(artifact, "SDD120", f"Citation `{decision_id}` does not resolve.", "Correct it or restore the decision.", artifact.line(decision_id, True))
                elif self._is_live(artifact) and target[1].get("status") in {"rejected", "superseded"}:
                    self.error(artifact, "SDD121", f"Live artifact cites `{decision_id}` with status `{target[1].get('status')}`.", "Cite the accepted replacement or reconcile content.", artifact.line(decision_id, True))
        if artifact.kind == "spec":
            return
        specs = self._related_specs(artifact)
        for family in ("FR", "NFR", "AC"):
            available = set().union(*(self.spec_ids[item.rel][family] for item in specs)) if specs else set()
            for number in IDS[family].findall(body):
                value = f"{family}-{number}"
                if value not in available:
                    self.error(artifact, "SDD122", f"Citation `{value}` does not resolve in a related spec.", "Relate the owning spec or correct the citation.", artifact.line(value, True))

    def _related_specs(self, artifact: Artifact) -> list[Artifact]:
        result: dict[str, Artifact] = {}
        frontier = [artifact]
        seen = {artifact.rel}
        if artifact.kind == "phase" and artifact.meta.get("plan"):
            plan = self.by_path.get(f"Plans/{artifact.meta['plan']}/README.md")
            if plan:
                frontier.append(plan)
                seen.add(plan.rel)
        if artifact.kind == "review" and isinstance(artifact.meta.get("review_of"), str):
            target = self.resolve(artifact.meta["review_of"])
            if target:
                frontier.append(target)
                seen.add(target.rel)
        while frontier:
            current = frontier.pop(0)
            related = current.meta.get("related", [])
            if not isinstance(related, list):
                continue
            for reference in related:
                target = self.resolve(reference) if isinstance(reference, str) else None
                if not target:
                    continue
                if target.kind == "spec":
                    result[target.rel] = target
                elif target.rel not in seen and target.kind in {"plan", "design", "review"}:
                    seen.add(target.rel)
                    frontier.append(target)
        return list(result.values())

    def _graphs(self) -> None:
        for plan in (item for item in self.artifacts if item.kind == "plan"):
            phases = plan.meta.get("phases")
            if not isinstance(phases, list):
                continue
            phase_ids = {str(item.get("id")) for item in phases if isinstance(item, dict)}
            phase_graph: dict[str, list[str]] = {}
            plan_tasks: dict[str, tuple[Artifact, dict[str, Any]]] = {}
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                phase_id = str(phase.get("id", ""))
                dependencies = self._deps(plan, phase, f"phase `{phase_id}`")
                phase_graph[phase_id] = dependencies
                for dependency in dependencies:
                    if dependency not in phase_ids:
                        self.error(plan, "SDD130", f"Phase `{phase_id}` depends on unknown `{dependency}`.", "Reference a phase in this plan.")
                    if dependency == phase_id:
                        self.error(plan, "SDD131", f"Phase `{phase_id}` depends on itself.", "Remove the self-dependency.")
                doc = phase.get("doc")
                target = self.by_path.get((Path(plan.rel).parent / str(doc)).as_posix()) if doc else None
                if target and isinstance(target.meta.get("tasks"), list):
                    for task in target.meta["tasks"]:
                        if isinstance(task, dict) and isinstance(task.get("id"), str):
                            plan_tasks[task["id"]] = (target, task)
            for cycle in cycles(phase_graph):
                self.error(plan, "SDD132", f"Phase dependency cycle: {' -> '.join(cycle)}.", "Make the graph acyclic.")
            task_graph: dict[str, list[str]] = {}
            for task_id, (phase, task) in plan_tasks.items():
                dependencies = self._deps(phase, task, f"task `{task_id}`")
                task_graph[task_id] = dependencies
                for dependency in dependencies:
                    if dependency not in plan_tasks:
                        self.error(phase, "SDD133", f"Task `{task_id}` depends on unknown `{dependency}`.", "Reference a task in this plan.")
                    if dependency == task_id:
                        self.error(phase, "SDD134", f"Task `{task_id}` depends on itself.", "Remove the self-dependency.")
            for cycle in cycles(task_graph):
                self.error(plan_tasks[cycle[0]][0], "SDD135", f"Task dependency cycle: {' -> '.join(cycle)}.", "Make the graph acyclic.")

    def _traceability(self) -> None:
        for plan in (item for item in self.artifacts if item.kind == "plan" and item.status in {"approved", "active", "complete"}):
            specs = self._related_specs(plan)
            if not specs:
                continue
            related = plan.meta.get("related", [])
            designs = [
                target
                for reference in related if isinstance(related, list) and isinstance(reference, str)
                if (target := self.resolve(reference)) is not None and target.kind == "design"
            ] if isinstance(related, list) else []
            plan_documents = [plan]
            phases = plan.meta.get("phases", [])
            if isinstance(phases, list):
                for phase in phases:
                    if not isinstance(phase, dict) or not isinstance(phase.get("doc"), str):
                        continue
                    target = self.by_path.get((Path(plan.rel).parent / phase["doc"]).as_posix())
                    if target:
                        plan_documents.append(target)
            plan_text_parts: list[str] = []
            for phase in plan_documents[1:]:
                tasks = phase.meta.get("tasks", [])
                if isinstance(tasks, list):
                    plan_text_parts.extend(str(task.get("verification", "")) for task in tasks if isinstance(task, dict))
                sections = self.sections(phase)
                acceptance = sections.get("Acceptance Criteria")
                if acceptance:
                    plan_text_parts.append(acceptance[1])
                for heading, (_, task_body) in sections.items():
                    if re.match(r"^\d+(?:[A-Z])?(?:-[A-Z])?\.\d+(?:\s*:|\s|$)", heading):
                        plan_text_parts.append(strip_completion_evidence(task_body))
            plan_text = "\n".join(plan_text_parts)
            design_text = "\n".join(no_comments(item.body) + "\n" + json.dumps(item.meta, default=str) for item in designs)
            for spec in specs:
                implicated = [spec.rel, *(design.rel for design in designs)]
                for family in ("FR", "NFR"):
                    for identifier in sorted(self.spec_ids[spec.rel][family]):
                        if identifier not in plan_text:
                            self.error(plan, "SDD160", f"Plan hierarchy never cites `{identifier}` from `{spec.rel}`.", "Cite the requirement in task verification/detail or phase acceptance criteria, or explicitly narrow the related specifications.", implicated=implicated)
                        if designs and identifier not in design_text:
                            self.error(plan, "SDD161", f"Related designs never cite `{identifier}` from `{spec.rel}`.", "Cite the requirement in a realizing design or remove an incorrect design relationship.", implicated=implicated)
                for identifier in sorted(self.spec_ids[spec.rel]["AC"]):
                    if identifier not in plan_text:
                        self.error(plan, "SDD162", f"Plan hierarchy never cites `{identifier}` from `{spec.rel}`.", "Cite the acceptance criterion in task verification/detail or phase acceptance criteria.", implicated=implicated)

    def _deps(self, artifact: Artifact, entry: dict[str, Any], label: str) -> list[str]:
        value = entry.get("depends_on", [])
        if value is None:
            return []
        if not isinstance(value, list):
            self.error(artifact, "SDD136", f"`depends_on` for {label} is not a list.", "Use a YAML list or omit it.")
            return []
        if any(not isinstance(item, (str, int)) for item in value):
            self.error(artifact, "SDD137", f"`depends_on` for {label} contains a non-scalar.", "Use only ids.")
        return [str(item) for item in value if isinstance(item, (str, int))]

    def _decision_links(self) -> None:
        for (repository_key, decision_id), (artifact, entry) in self.decisions.items():
            if entry.get("status") == "superseded" and not entry.get("superseded_by"):
                self.error(artifact, "SDD140", f"Superseded `{decision_id}` lacks `superseded_by`.", "Link the accepted replacement.")
            for field, reverse in (("supersedes", "superseded_by"), ("superseded_by", "supersedes")):
                value = entry.get(field)
                if not value:
                    continue
                target = self.decisions.get((repository_key, str(value)))
                if target is None:
                    self.error(artifact, "SDD141", f"Decision `{decision_id}` {field} unknown `{value}`.", "Reference an existing decision.")
                elif target[1].get(reverse) != decision_id:
                    self.error(artifact, "SDD142", f"Decision `{decision_id}` {field} link is not reciprocated.", f"Add matching `{reverse}`.")
            scope = entry.get("scope", [])
            if not isinstance(scope, list):
                self.error(artifact, "SDD143", f"Decision `{decision_id}` scope is not a list.", "Use a YAML list.")
                continue
            for reference in scope:
                if not isinstance(reference, str):
                    self.error(artifact, "SDD144", f"Decision `{decision_id}` has a non-string scope.", "Use repository-relative paths.")
                    continue
                target = self.resolve(reference)
                filesystem = (Path(repository_key) / reference).resolve()
                if target is None and not filesystem.exists():
                    self.error(artifact, "SDD145", f"Decision `{decision_id}` scope `{reference}` does not resolve.", "Point it at an existing artifact or repository path.")
                elif target and entry.get("status") == "accepted" and decision_id not in target.source:
                    self.error(target, "SDD146", f"Artifact is governed by `{decision_id}` but does not cite it.", f"Cite `{decision_id}` or narrow its scope.")
        accepted = [(key[0], key[1], value[0], value[1]) for key, value in self.decisions.items() if value[1].get("status") == "accepted"]
        for index, (left_repo, left_id, artifact, left) in enumerate(accepted):
            for right_repo, right_id, _, right in accepted[index + 1 :]:
                if left_repo != right_repo:
                    continue
                if not self._scopes_overlap(left.get("scope"), right.get("scope")):
                    continue
                if normalized(left.get("question")) and normalized(left.get("question")) == normalized(right.get("question")) and normalized(left.get("statement")) != normalized(right.get("statement")):
                    self.candidate(artifact, "SDD147", f"`{left_id}` and `{right_id}` answer the same question differently.", "Judge whether they conflict, refine one another, or have disjoint scope.")
                if chosen_rejected(left, right) or chosen_rejected(right, left):
                    self.candidate(artifact, "SDD148", f"`{left_id}` and `{right_id}` choose and reject the same option.", "Judge whether they conflict or have disjoint scope.")
                left_term = definition_term(left)
                right_term = definition_term(right)
                if left_term and left_term == right_term and normalized(left.get("statement")) != normalized(right.get("statement")):
                    self.candidate(artifact, "SDD149", f"`{left_id}` and `{right_id}` define `{left_term}` differently.", "Judge whether the definitions conflict or have disjoint scope.")

    def _focused_decision_logs(self) -> None:
        candidates: list[Path] = []
        internal = self.root / "Decisions"
        canonical = internal / "decisions.md"
        if canonical.is_file():
            candidates.append(canonical)
        else:
            candidates.extend(sorted(internal.glob("archive-*.md"))[:1])
        for repository in {self.repo, *self.plan_repos.values()}:
            canonical = repository / "DECISIONS.md"
            if canonical.is_file():
                candidates.append(canonical)
            else:
                candidates.extend(sorted(repository.glob("archive-*.md"))[:1])
        seen: set[Path] = set()
        for path in candidates:
            directory = path.parent.resolve()
            if directory in seen:
                continue
            seen.add(directory)
            diagnostics, _, _ = validate_decision_ledgers(
                path,
                history=self.identity_mode != "historical" and git_root(path) is not None,
            )
            for item in diagnostics:
                path = item.path
                try:
                    path = Path(path).resolve().relative_to(self.root).as_posix()
                except ValueError:
                    pass
                self.out.append(
                    Diagnostic(
                        item.severity,
                        item.code,
                        str(path),
                        item.line,
                        item.message,
                        item.correction,
                    )
                )

    def _is_live(self, artifact: Artifact) -> bool:
        if artifact.kind in {"debrief", "retro"}:
            return False
        return artifact.status not in {"archived", "superseded"}

    def _scopes_overlap(self, left: Any, right: Any) -> bool:
        if not isinstance(left, list) or not left or not isinstance(right, list) or not right:
            return True
        for left_item in left:
            for right_item in right:
                if not isinstance(left_item, str) or not isinstance(right_item, str):
                    continue
                left_path = left_item.rstrip("/")
                right_path = right_item.rstrip("/")
                if left_path == right_path or left_path.startswith(right_path + "/") or right_path.startswith(left_path + "/"):
                    return True
                left_artifact = self.resolve(left_item)
                right_artifact = self.resolve(right_item)
                if left_artifact and right_artifact and (
                    self._artifacts_connected(left_artifact, right_artifact)
                    or self._artifacts_connected(right_artifact, left_artifact)
                ):
                    return True
        return False

    def _artifacts_connected(self, left: Artifact, right: Artifact) -> bool:
        frontier = [(left, 0)]
        seen = {left.rel}
        while frontier:
            current, depth = frontier.pop(0)
            if current.rel == right.rel:
                return True
            if depth >= 2:
                continue
            related = current.meta.get("related", [])
            if not isinstance(related, list):
                continue
            for reference in related:
                target = self.resolve(reference) if isinstance(reference, str) else None
                if target and target.rel not in seen:
                    seen.add(target.rel)
                    frontier.append((target, depth + 1))
        return False


def open_question_items(body: str) -> list[str]:
    value = visible_markdown(body).strip()
    if not value or value.lower().rstrip(".") in {"none", "n/a"}:
        return []
    items: list[str] = []
    current: str | None = None
    for line in value.splitlines():
        match = re.match(r"^\s*-\s*(.*?)\s*$", line)
        if match:
            if current is not None:
                items.append(current)
            current = match.group(1)
            continue
        continuation = line.strip()
        if not continuation:
            continue
        if current is None:
            items.append(continuation)
        else:
            current = f"{current} {continuation}".strip()
    if current is not None:
        items.append(current)
    return [item for item in items if item.lower().rstrip(".") not in {"none", "n/a"}]


def read_utf8(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def parse_frontmatter_source(source: str) -> dict[str, Any] | None:
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return None
    try:
        value = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError:
        return None
    return value if isinstance(value, dict) else None


def spec_definition_ids(source: str) -> set[str]:
    body = visible_markdown(source)
    return set().union(*(set(pattern.findall(body)) for pattern in DEFINITIONS.values()))


def spec_retained_ids(source: str) -> set[str]:
    result = spec_definition_ids(source)
    identifier = r"((?:FR|NFR|AC)-\d{2,})"
    removed = re.compile(
        rf"^\s*-\s+(?:\[[ xX]\]\s+)?\*\*{identifier}\*\*\s*:\s*removed\s+[—-]\s+see\s+\S.*$",
        re.IGNORECASE,
    )
    struck = re.compile(
        rf"^\s*-\s+(?:\[[ xX]\]\s+)?~~\*\*{identifier}\*\*\s*:\s*\S.*~~\s*$"
    )
    for line in visible_markdown(source).splitlines():
        match = removed.match(line) or struck.match(line)
        if match:
            result.add(match.group(1))
    return result


def frontmatter_entry_ids(source: str, field: str) -> set[str]:
    meta = parse_frontmatter_source(source)
    entries = meta.get(field) if meta else None
    if not isinstance(entries, list):
        return set()
    return {
        str(entry["id"])
        for entry in entries
        if isinstance(entry, dict) and entry.get("id") not in (None, "")
    }


def completion_evidence_body(task_body: str) -> str | None:
    bodies = heading_bodies(task_body, 3, "Completion Evidence")
    return bodies[0] if len(bodies) == 1 else None


def markdown_lines(body: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    fence: tuple[str, int] | None = None
    in_comment = False
    for raw in body.splitlines(keepends=True):
        visible_parts: list[str] = []
        remaining = raw
        while remaining:
            if in_comment:
                closing = remaining.find("-->")
                if closing < 0:
                    remaining = ""
                    break
                in_comment = False
                remaining = remaining[closing + 3 :]
                continue
            opening = remaining.find("<!--")
            if opening < 0:
                visible_parts.append(remaining)
                break
            visible_parts.append(remaining[:opening])
            remaining = remaining[opening + 4 :]
            in_comment = True
        visible_text = "".join(visible_parts)
        if raw.endswith("\n") and not visible_text.endswith("\n"):
            visible_text += "\n"
        stripped = visible_text.lstrip(" ")
        indent = len(visible_text) - len(stripped)
        if fence is not None:
            marker, length = fence
            if indent <= 3 and re.match(rf"^{re.escape(marker)}{{{length},}}\s*$", stripped.rstrip("\r\n")):
                fence = None
            result.append((raw, "\n" if raw.endswith("\n") else ""))
            continue
        opener = re.match(r"^(`{3,}|~{3,})", stripped) if indent <= 3 else None
        if opener:
            token = opener.group(1)
            fence = (token[0], len(token))
            result.append((raw, "\n" if raw.endswith("\n") else ""))
            continue
        result.append((raw, visible_text))
    return result


def visible_markdown(body: str) -> str:
    return "".join(visible for _, visible in markdown_lines(body))


def heading_bodies(body: str, level: int, label: str) -> list[str]:
    lines = markdown_lines(body)
    marker = re.compile(rf"^{'#' * level}\s+{re.escape(label)}\s*$")
    starts = [index for index, (_, visible) in enumerate(lines) if marker.match(visible.rstrip("\r\n"))]
    result: list[str] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            _, visible = lines[index]
            if re.match(rf"^#{{1,{level}}}\s+", visible):
                end = index
                break
        result.append(no_comments("".join(raw for raw, _ in lines[start + 1 : end])).strip())
    return result


def rollup_bodies(body: str, label: str) -> list[str]:
    lines = markdown_lines(body)
    marker = re.compile(rf"^###\s+{re.escape(label)}\s*$")
    starts = [index for index, (_, visible) in enumerate(lines) if marker.match(visible.rstrip("\r\n"))]
    result: list[str] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            _, visible = lines[index]
            if re.match(r"^#{1,3}\s+", visible):
                end = index
                break
        result.append(no_comments("".join(raw for raw, _ in lines[start + 1 : end])).strip())
    return result


def encode_path_bytes(value: bytes) -> str:
    safe = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/"
    return "".join(chr(byte) if byte in safe else f"%{byte:02X}" for byte in value)


def git_output(repository: Path, *args: str) -> tuple[bytes | None, str | None]:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None, result.stderr.decode("utf-8", errors="replace").strip()
    return result.stdout, None


def worktree_snapshot_entry(repository: Path, relative: bytes, base: str) -> tuple[tuple[str, str, int, str] | None, str | None]:
    value = os.fsdecode(relative)
    target = repository / value
    tree, error = git_output(repository, "ls-tree", "-z", base, "--", value)
    if error:
        return None, error
    base_mode = tree.split(b" ", 1)[0].decode("ascii") if tree else ""
    if base_mode == "160000":
        return None, f"changed Gitlink `{value}` requires a separate nested-repository snapshot"
    try:
        info = target.lstat()
    except FileNotFoundError:
        return ("D", "000000", 0, "-"), None
    mode = f"{stat.S_IMODE(info.st_mode) | stat.S_IFMT(info.st_mode):06o}"
    if stat.S_ISREG(info.st_mode):
        content = target.read_bytes()
        current_type = "file"
    elif stat.S_ISLNK(info.st_mode):
        content = os.fsencode(os.readlink(target))
        current_type = "symlink"
    else:
        return None, f"changed path `{value}` has unsupported file type"
    base_type = "symlink" if base_mode == "120000" else "file" if base_mode.startswith("100") else ""
    state = "A" if not base_mode else "T" if base_type != current_type else "M"
    return (state, mode, len(content), hashlib.sha256(content).hexdigest()), None


def compare_dirty_git_snapshot(
    path: Path,
    content: bytes,
    repository: Path,
    base: str,
    exclusions: set[str],
    ignored_inputs: set[str] | None = None,
    directory_inputs: set[str] | None = None,
) -> list[str]:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        return []
    lines = text.splitlines()
    if not lines or lines[0] != "sdd-dirty-snapshot-v1":
        return []
    manifest: dict[str, tuple[str, str, int, str]] = {}
    directories: dict[str, str] = {}
    for line in lines[2:]:
        fields = line.split("\t")
        if fields[0] == "entry" and len(fields) == 6:
            try:
                manifest[fields[5]] = (fields[1], fields[2], int(fields[3]), fields[4])
            except ValueError:
                return []
        elif fields[0] == "directory" and len(fields) == 3:
            directories[fields[2]] = fields[1]

    errors: list[str] = []
    commit, error = git_output(repository, "cat-file", "-e", f"{base}^{{commit}}")
    if error or commit is None:
        return [f"base revision `{base}` is unavailable"]
    unmerged, error = git_output(repository, "ls-files", "-u", "-z")
    if error:
        return [f"cannot inspect index: {error}"]
    if unmerged:
        errors.append("index contains unmerged entries")

    changed, error = git_output(repository, "diff", "--name-only", "--no-renames", "-z", base, "--")
    if error:
        return [f"cannot compare base to worktree: {error}"]
    untracked, error = git_output(repository, "ls-files", "--others", "--exclude-standard", "-z")
    if error:
        return [f"cannot enumerate untracked files: {error}"]
    paths = {item for value in (changed or b"", untracked or b"") for item in value.split(b"\0") if item}
    expected_directories = set(directory_inputs or set())
    ignored_directory_roots: set[str] = set()
    for ignored in ignored_inputs or set():
        if not valid_decoded_path(os.fsencode(ignored)):
            errors.append(f"ignored input path `{ignored}` is not canonical and repository-relative")
            continue
        ignored_check, ignored_error = git_output(repository, "check-ignore", "-q", "--", ignored)
        if ignored_error or ignored_check is None:
            errors.append(f"recorded ignored input `{ignored}` is not ignored by Git")
            continue
        target = repository / ignored
        try:
            info = target.lstat()
        except FileNotFoundError:
            errors.append(f"recorded ignored input `{ignored}` does not exist")
            continue
        if stat.S_ISDIR(info.st_mode):
            expected_directories.add(ignored)
            ignored_directory_roots.add(ignored)
        else:
            paths.add(os.fsencode(ignored))
    directory_roots = set(expected_directories)
    for declared in directory_roots:
        target = repository / declared
        try:
            info = target.lstat()
        except FileNotFoundError:
            errors.append(f"recorded directory input `{declared}` does not exist")
            continue
        if not stat.S_ISDIR(info.st_mode):
            errors.append(f"recorded directory input `{declared}` is not a directory")
            continue
        for current_root, dirnames, filenames in os.walk(target, followlinks=False):
            current_path = Path(current_root)
            current_relative = current_path.relative_to(repository).as_posix()
            expected_directories.add(current_relative)
            for dirname in list(dirnames):
                child = current_path / dirname
                if child.is_symlink():
                    dirnames.remove(dirname)
                    if any(current_relative == root or current_relative.startswith(root + "/") for root in ignored_directory_roots):
                        paths.add(os.fsencode(child.relative_to(repository).as_posix()))
            if any(current_relative == root or current_relative.startswith(root + "/") for root in ignored_directory_roots):
                for filename in filenames:
                    paths.add(os.fsencode((current_path / filename).relative_to(repository).as_posix()))
    tree, tree_error = git_output(repository, "ls-tree", "-rz", "--full-tree", base)
    if tree_error:
        errors.append(f"cannot enumerate base tree modes: {tree_error}")
    else:
        for record in (tree or b"").split(b"\0"):
            if not record or b"\t" not in record:
                continue
            header, relative = record.split(b"\t", 1)
            mode = header.split(b" ", 1)[0]
            if not mode.startswith(b"100"):
                continue
            decoded = os.fsdecode(relative)
            if decoded in exclusions:
                continue
            try:
                current = (repository / decoded).lstat()
            except FileNotFoundError:
                continue
            actual_mode = f"{stat.S_IMODE(current.st_mode) | stat.S_IFMT(current.st_mode):06o}".encode()
            if actual_mode != mode:
                paths.add(relative)
    expected: dict[str, tuple[str, str, int, str]] = {}
    for relative in paths:
        decoded = os.fsdecode(relative)
        if decoded in exclusions:
            continue
        encoded = encode_path_bytes(relative)
        entry, entry_error = worktree_snapshot_entry(repository, relative, base)
        if entry_error:
            errors.append(entry_error)
        elif entry:
            expected[encoded] = entry

    missing = sorted(set(expected) - set(manifest))
    extra = sorted(set(manifest) - set(expected))
    if missing:
        errors.append(f"manifest omits changed paths: {', '.join(missing)}")
    if extra:
        errors.append(f"manifest contains unchanged or excluded paths: {', '.join(extra)}")
    for encoded in sorted(set(expected) & set(manifest)):
        if expected[encoded] != manifest[encoded]:
            errors.append(f"manifest metadata for `{encoded}` is {manifest[encoded]}, expected {expected[encoded]}")

    staged, error = git_output(repository, "diff", "--cached", "--name-only", "-z", base, "--")
    if error:
        errors.append(f"cannot inspect staged paths: {error}")
        staged = b""
    staged_paths = {item for item in (staged or b"").split(b"\0") if item}
    index_output, error = git_output(repository, "ls-files", "-s", "-z", "--")
    if error:
        errors.append(f"cannot inspect index entries: {error}")
        index_output = b""
    index: dict[bytes, tuple[str, str]] = {}
    for record in (index_output or b"").split(b"\0"):
        if not record or b"\t" not in record:
            continue
        header, relative = record.split(b"\t", 1)
        fields = header.decode("ascii", errors="replace").split()
        if len(fields) == 3 and fields[2] == "0":
            index[relative] = (fields[0], fields[1])
    for relative in sorted(staged_paths):
        decoded = os.fsdecode(relative)
        if decoded in exclusions:
            continue
        indexed = index.get(relative)
        target = repository / decoded
        try:
            info = target.lstat()
        except FileNotFoundError:
            info = None
        if indexed is None:
            if info is not None:
                errors.append(f"staged path `{encode_path_bytes(relative)}` is absent from the index but present in the worktree")
            continue
        if info is None:
            errors.append(f"staged path `{encode_path_bytes(relative)}` is present in the index but absent from the worktree")
            continue
        if stat.S_ISREG(info.st_mode):
            worktree_mode = "100755" if info.st_mode & 0o111 else "100644"
            worktree_content = target.read_bytes()
        elif stat.S_ISLNK(info.st_mode):
            worktree_mode = "120000"
            worktree_content = os.fsencode(os.readlink(target))
        else:
            errors.append(f"staged path `{encode_path_bytes(relative)}` has unsupported worktree type")
            continue
        blob, blob_error = git_output(repository, "cat-file", "blob", indexed[1])
        if blob_error or blob is None:
            errors.append(f"cannot read index blob for `{encode_path_bytes(relative)}`")
            continue
        if indexed[0] != worktree_mode or blob != worktree_content:
            errors.append(f"staged path `{encode_path_bytes(relative)}` differs from worktree bytes or mode")

    expected_encoded_directories = {encode_path_bytes(os.fsencode(value)) for value in expected_directories}
    missing_directories = sorted(expected_encoded_directories - set(directories))
    extra_directories = sorted(set(directories) - expected_encoded_directories)
    if missing_directories:
        errors.append(f"manifest omits declared directories: {', '.join(missing_directories)}")
    if extra_directories:
        errors.append(f"manifest contains undeclared directories: {', '.join(extra_directories)}")
    for encoded, recorded_mode in directories.items():
        decoded = unquote_to_bytes(encoded)
        if not valid_decoded_path(decoded):
            errors.append(f"recorded directory `{encoded}` is not repository-relative")
            continue
        target = repository / os.fsdecode(decoded)
        try:
            target.resolve().relative_to(repository.resolve())
        except ValueError:
            errors.append(f"recorded directory `{encoded}` resolves outside the repository")
            continue
        try:
            info = target.lstat()
        except FileNotFoundError:
            errors.append(f"recorded directory `{encoded}` does not exist")
            continue
        actual_mode = f"{stat.S_IMODE(info.st_mode) | stat.S_IFMT(info.st_mode):06o}"
        if not stat.S_ISDIR(info.st_mode) or actual_mode != recorded_mode:
            errors.append(f"recorded directory `{encoded}` mode is `{recorded_mode}`, expected `{actual_mode}`")
    return errors


def evidence_value(body: str, label: str) -> str | None:
    match = re.search(rf"^\s*-\s+{re.escape(label)}:\s*(.+?)\s*$", body, re.MULTILINE)
    return match.group(1) if match else None


def digest_location(value: str) -> str | None:
    match = re.search(r"\bat\s+`?([^`;]+?)`?(?:;|$)", value)
    return match.group(1).strip() if match else None


def parse_exclusions(value: str | None) -> set[str]:
    scalar = markdown_scalar(value)
    if not scalar or scalar.lower() == "none":
        return set()
    return {part.strip().strip("`") for part in scalar.split(",") if part.strip().strip("`")}


def parse_inventory_paths(value: str | None) -> tuple[set[str], str | None]:
    scalar = markdown_scalar(value)
    if not scalar:
        return set(), "value is empty"
    if scalar.lower().startswith("none with ") and scalar[10:].strip():
        return set(), None
    match = re.search(r"\bpaths:\s*(.+?)(?:;|$)", scalar, re.IGNORECASE)
    if not match:
        return set(), "value does not use a documented inventory form"
    paths = {
        part.strip().strip("`")
        for part in match.group(1).split(",")
        if part.strip().strip("`")
    }
    basis = scalar[match.end() :].lstrip("; ").strip()
    if not paths or not basis:
        return set(), "paths or inspection/digest basis is empty"
    if any(not valid_decoded_path(os.fsencode(path)) for path in paths):
        return set(), "a path is not canonical and repository-relative"
    return paths, None


def parse_recorded_inputs(value: str) -> set[str]:
    marker = re.search(r"\binputs:\s*(.+)$", value)
    if not marker:
        return set()
    return {part.strip().strip("`") for part in marker.group(1).split(",") if part.strip().strip("`")}


def markdown_scalar(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if len(result) >= 2 and result[0] == result[-1] == "`":
        result = result[1:-1].strip()
    return result


def evidence_rows(body: str) -> list[tuple[str, tuple[str, str, str, str]]]:
    rows: list[tuple[str, tuple[str, str, str, str]]] = []
    active: str | None = None
    for raw_line in visible_markdown(body).splitlines():
        cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
        if cells == ["Command", "Working directory", "Result", "Observable evidence"]:
            active = "command"
            continue
        if cells == ["Tool / inspection", "Context", "Result", "Observable evidence"]:
            active = "tool"
            continue
        if not active:
            continue
        if len(cells) == 4 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != 4 or not raw_line.lstrip().startswith("|"):
            active = None
            continue
        values = tuple(markdown_scalar(cell) or "" for cell in cells)
        if all(values) and not any("<" in value and ">" in value for value in values):
            rows.append((active, values))  # type: ignore[arg-type]
    return rows


def validate_intent_projection(content: bytes) -> tuple[str | None, set[str], list[tuple[str, str, bytes]]]:
    header = b"sdd-intent-v2\n"
    if not content.startswith(header):
        return "missing `sdd-intent-v2` header", set(), []
    offset = len(header)
    inputs: set[str] = set()
    records: list[tuple[str, str, bytes]] = []
    previous_reference = ""
    while offset < len(content):
        newline = content.find(b"\n", offset)
        if newline < 0:
            return "unterminated input header", inputs, records
        try:
            fields = content[offset:newline].decode("utf-8").split("\t")
        except UnicodeDecodeError:
            return "input header is not UTF-8", inputs, records
        if len(fields) != 4 or fields[0] != "input" or fields[1] not in {"artifact", "decision"} or not valid_encoded_path(fields[2]):
            return "invalid input header", inputs, records
        reference = unquote(fields[2])
        if reference in inputs:
            return "duplicate input reference", inputs, records
        if fields[2] < previous_reference:
            return "input records are not encoded-reference sorted", inputs, records
        previous_reference = fields[2]
        try:
            byte_count = int(fields[3])
        except ValueError:
            return "input byte-count is not decimal", inputs, records
        if byte_count < 0 or newline + 1 + byte_count > len(content):
            return "input byte-count exceeds projection length", inputs, records
        payload = content[newline + 1 : newline + 1 + byte_count]
        if fields[1] == "artifact":
            if not payload.startswith(b"---\n") or b"\n---\n" not in payload:
                return "artifact projection payload lacks YAML frontmatter", inputs, records
            yaml_end = payload.find(b"\n---\n", 4)
            try:
                projected_meta = yaml.safe_load(payload[4:yaml_end].decode("utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError):
                return "artifact projection frontmatter is invalid", inputs, records
            if not isinstance(projected_meta, dict):
                return "artifact projection frontmatter is not a mapping", inputs, records
            required = {"title", "type", "created"}
            if not required.issubset(projected_meta) or "status" in projected_meta or "updated" in projected_meta:
                return "artifact projection has missing common fields or retained lifecycle fields", inputs, records
            artifact_type = projected_meta.get("type")
            if artifact_type not in {"plan", "phase", "spec", "design"}:
                return "artifact projection has unsupported type", inputs, records
            projected_body = payload[yaml_end + 5 :].decode("utf-8", errors="replace")
            for heading in REQUIRED_HEADINGS.get(str(artifact_type), ()):
                if not re.search(rf"^##\s+{re.escape(heading)}\s*$", projected_body, re.MULTILINE):
                    return f"artifact projection lacks `## {heading}`", inputs, records
            if artifact_type in {"plan", "phase"} and PENDING not in projected_body:
                return "plan/phase projection lacks normalized pending evidence", inputs, records
        else:
            if not payload.lstrip().startswith(b"- id: D-"):
                return "decision projection payload does not start with a decision id", inputs, records
            try:
                projected_decision = yaml.safe_load(payload.decode("utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError):
                return "decision projection YAML is invalid", inputs, records
            if not isinstance(projected_decision, list) or len(projected_decision) != 1 or not isinstance(projected_decision[0], dict):
                return "decision projection is not exactly one entry", inputs, records
            if projected_decision[0].get("id") != reference.rsplit("#", 1)[-1]:
                return "decision projection id does not match its reference", inputs, records
        inputs.add(reference)
        records.append((fields[1], reference, payload))
        offset = newline + 1 + byte_count
    return (None, inputs, records) if records else ("projection contains no inputs", inputs, records)


def validate_snapshot(
    path: Path,
    content: bytes,
    expected_vcs: str = "",
    expected_revision: str = "",
    expected_exclusions: set[str] | None = None,
) -> list[str]:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        return ["manifest is not ASCII"]
    if not text.endswith("\n"):
        return ["manifest has no final LF"]
    lines = text.splitlines()
    if not lines:
        return ["manifest is empty"]
    if lines[0] == "sdd-dirty-snapshot-v1":
        expected_fields = 6
        if len(lines) < 2 or not re.fullmatch(r"base\t[0-9a-fA-F]{40}", lines[1]):
            return ["dirty manifest has no full Git base revision"]
        if expected_vcs and expected_vcs not in {"git", "git-worktree"}:
            return [f"dirty Git manifest contradicts recorded VCS `{expected_vcs}`"]
        if expected_revision and lines[1].split("\t", 1)[1].lower() != expected_revision.removesuffix("-dirty").lower():
            return ["dirty manifest base does not match recorded revision/base"]
    elif lines[0] == "sdd-content-snapshot-v1":
        expected_fields = 7
        if len(lines) < 3 or lines[1] not in {"vcs\tperforce", "vcs\tnone"} or not lines[2].startswith("base\t"):
            return ["content manifest has invalid VCS/base headers"]
        manifest_vcs = lines[1].split("\t", 1)[1]
        if expected_vcs and manifest_vcs != expected_vcs:
            return [f"content manifest VCS `{manifest_vcs}` contradicts recorded VCS `{expected_vcs}`"]
        manifest_base = lines[2].split("\t", 1)[1]
        if expected_revision and manifest_base != expected_revision:
            return ["content manifest base does not match recorded revision/base"]
    else:
        return ["unknown snapshot manifest header"]
    errors: list[str] = []
    entries = 0
    previous_rank = 0
    previous_path: dict[str, str] = {}
    seen_paths: set[str] = set()
    manifest_exclusions: set[str] = set()
    for line in lines[1:]:
        kind = line.split("\t", 1)[0]
        if lines[0] == "sdd-dirty-snapshot-v1":
            ranks = {"base": 0, "exclude": 1, "directory": 2, "entry": 3}
        else:
            ranks = {"vcs": 0, "base": 0, "exclude": 1, "have": 2, "entry": 3}
        if kind not in ranks:
            errors.append(f"unknown manifest record `{kind}`")
            continue
        rank = ranks[kind]
        if rank < previous_rank:
            errors.append(f"record `{kind}` is out of canonical group order")
        previous_rank = max(previous_rank, rank)
        fields = line.split("\t")
        if kind == "exclude":
            if len(fields) != 2 or not valid_encoded_path(fields[-1]):
                errors.append("invalid exclude record")
            elif fields[-1] < previous_path.get(kind, ""):
                errors.append("exclude records are not path-sorted")
            previous_path[kind] = fields[-1]
            if len(fields) == 2:
                manifest_exclusions.add(unquote(fields[-1]))
            continue
        if kind == "directory":
            if len(fields) != 3 or not re.fullmatch(r"[0-7]{6}", fields[1]) or not valid_encoded_path(fields[-1]):
                errors.append("invalid directory record")
            elif fields[-1] < previous_path.get(kind, ""):
                errors.append("directory records are not path-sorted")
            previous_path[kind] = fields[-1]
            continue
        if kind == "have":
            if len(fields) != 3 or not fields[1] or not valid_encoded_path(fields[2]):
                errors.append("invalid have record")
            elif fields[2] < previous_path.get(kind, ""):
                errors.append("have records are not path-sorted")
            previous_path[kind] = fields[2]
            continue
        if kind != "entry":
            continue
        entries += 1
        if len(fields) != expected_fields:
            errors.append(f"entry has {len(fields)} fields, expected {expected_fields}")
            continue
        if expected_fields == 6:
            _, state, mode, size_text, digest, encoded_path, *extra = fields
            entry_type = "-" if state == "D" else "f"
            if state not in {"A", "M", "D", "T"}:
                errors.append(f"entry `{encoded_path}` has invalid state `{state}`")
        else:
            _, state, entry_type, mode, size_text, digest, encoded_path, *extra = fields
            if state not in {"P", "D"} or entry_type not in {"d", "f", "l", "-"}:
                errors.append(f"entry `{encoded_path}` has invalid state/type")
        if not valid_encoded_path(encoded_path):
            errors.append(f"entry path `{encoded_path}` is not canonically encoded")
        if encoded_path in seen_paths:
            errors.append(f"entry path `{encoded_path}` is duplicated")
        seen_paths.add(encoded_path)
        if encoded_path < previous_path.get(kind, ""):
            errors.append("entry records are not path-sorted")
        previous_path[kind] = encoded_path
        if not re.fullmatch(r"[0-7]{6}", mode):
            errors.append(f"entry `{encoded_path}` has invalid mode `{mode}`")
        try:
            size = int(size_text)
        except ValueError:
            errors.append(f"entry `{encoded_path}` has non-decimal size")
            continue
        if expected_fields == 6 and state == "D" and (mode != "000000" or size != 0 or digest != "-"):
            errors.append(f"deleted entry `{encoded_path}` has noncanonical metadata")
        if expected_fields == 7 and state == "D" and (entry_type != "-" or mode != "000000" or size != 0 or digest != "-"):
            errors.append(f"deleted entry `{encoded_path}` has noncanonical metadata")
        if expected_fields == 7 and entry_type == "d" and (size != 0 or digest != "-"):
            errors.append(f"directory entry `{encoded_path}` has noncanonical metadata")
        if digest == "-":
            if size != 0:
                errors.append(f"entry `{encoded_path}` has no digest but nonzero size")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"entry `{encoded_path}` has invalid SHA-256")
            continue
        if entry_type == "d":
            errors.append(f"directory entry `{encoded_path}` unexpectedly has content")
            continue
        obj = Path(f"{path}.contents") / digest
        if not obj.is_file():
            errors.append(f"content object `{obj.name}` is missing")
            continue
        object_content = obj.read_bytes()
        if len(object_content) != size:
            errors.append(f"content object `{obj.name}` has size {len(object_content)}, expected {size}")
        if hashlib.sha256(object_content).hexdigest() != digest:
            errors.append(f"content object `{obj.name}` does not match its digest")
    if not entries:
        errors.append("manifest contains no entries")
    if expected_exclusions is not None and manifest_exclusions != expected_exclusions:
        errors.append(
            f"manifest exclusions {sorted(manifest_exclusions)} do not match recorded exclusions {sorted(expected_exclusions)}"
        )
    return errors


def valid_encoded_path(value: str) -> bool:
    if not value or value.startswith("/") or value.endswith("/") or "//" in value:
        return False
    if any(part in {".", ".."} for part in value.split("/")):
        return False
    if re.fullmatch(r"(?:[A-Za-z0-9._/-]|%[0-9A-F]{2})+", value) is None:
        return False
    decoded = unquote_to_bytes(value)
    return valid_decoded_path(decoded) and encode_path_bytes(decoded) == value


def valid_decoded_path(value: bytes) -> bool:
    return bool(value) and not value.startswith(b"/") and not value.endswith(b"/") and all(
        part not in {b"", b".", b".."} for part in value.split(b"/")
    )


def resolution_entry(log: str, finding_id: str) -> str:
    match = re.search(rf"^###\s+{re.escape(finding_id)}\b.*$", log, re.MULTILINE)
    if not match:
        return ""
    following = re.search(r"^###\s+F-\d+\b", log[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(log)
    return log[match.start() : end]


def no_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def strip_completion_evidence(text: str) -> str:
    return re.sub(
        r"^###\s+Completion Evidence\s*$[\s\S]*?(?=^###\s+|\Z)",
        "",
        no_comments(text),
        flags=re.MULTILINE,
    )


def project_artifact(artifact: Artifact) -> bytes:
    lines = artifact.source.splitlines(keepends=True)
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    projected_frontmatter: list[str] = []
    for line in lines[1:end]:
        if re.match(r"^(?:updated|status):\s*[^|>{}\[\]]+\n$", line):
            continue
        if artifact.kind in {"plan", "phase"} and re.match(r"^\s+status:\s*[^|>{}\[\]]+\n$", line):
            continue
        projected_frontmatter.append(line)
    body = "".join(lines[end + 1 :])
    if artifact.kind == "plan":
        body = normalize_evidence_section(body, 2, "Plan Completion Evidence")
    elif artifact.kind == "phase":
        body = normalize_all_task_evidence(body)
        body = normalize_evidence_section(body, 2, "Phase Completion Evidence")
        body = normalize_checkboxes(body, 3, "Subtasks")
        body = normalize_checkboxes(body, 2, "Acceptance Criteria")
    return ("---\n" + "".join(projected_frontmatter) + "---\n" + body).encode("utf-8")


def normalize_evidence_section(text: str, level: int, heading: str) -> str:
    marker = re.compile(rf"^{'#' * level}\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = marker.search(text)
    if not match:
        return text
    following = re.search(rf"^#{{1,{level}}}\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[: match.end()] + "\n\n" + PENDING + "\n" + text[end:]


def normalize_all_task_evidence(text: str) -> str:
    marker = re.compile(r"^###\s+Completion Evidence\s*$", re.MULTILINE)
    offset = 0
    while match := marker.search(text, offset):
        following = re.search(r"^#{1,3}\s+", text[match.end() :], re.MULTILINE)
        end = match.end() + following.start() if following else len(text)
        replacement = text[: match.end()] + "\n\n" + PENDING + "\n" + text[end:]
        offset = match.end() + len(PENDING) + 2
        text = replacement
    return text


def normalize_checkboxes(text: str, level: int, heading: str) -> str:
    marker = re.compile(rf"^{'#' * level}\s+{re.escape(heading)}\s*$", re.MULTILINE)
    offset = 0
    while match := marker.search(text, offset):
        following = re.search(rf"^#{{1,{level}}}\s+", text[match.end() :], re.MULTILINE)
        end = match.end() + following.start() if following else len(text)
        section = re.sub(r"\[[xX]\]", "[ ]", text[match.end() : end])
        text = text[: match.end()] + section + text[end:]
        offset = match.end() + len(section)
    return text


def project_decision_entry(artifact: Artifact, decision_id: str) -> bytes | None:
    lines = artifact.source.splitlines(keepends=True)
    pattern = re.compile(rf"^(\s*)- id:\s*{re.escape(decision_id)}\s*$")
    start = None
    indent = ""
    for index, line in enumerate(lines):
        match = pattern.match(line.rstrip("\n"))
        if match:
            start = index
            indent = match.group(1)
            break
    if start is None:
        return None
    end = len(lines)
    next_entry = re.compile(rf"^{re.escape(indent)}- id:\s*D-\d+")
    for index in range(start + 1, len(lines)):
        if next_entry.match(lines[index]) or lines[index].strip() == "---":
            end = index
            break
    return "".join(lines[start:end]).encode("utf-8")


def ipfs_sha256(uri: str) -> str | None:
    parsed = urlparse(uri)
    raw = parsed.netloc or parsed.path.lstrip("/").split("/", 1)[0]
    if raw == "ipfs":
        raw = parsed.path.lstrip("/").split("/", 1)[0]
    try:
        if raw.startswith("Qm"):
            decoded = base58_decode(raw)
            return decoded[2:].hex() if decoded[:2] == b"\x12\x20" and len(decoded) == 34 else None
        if raw.startswith("b"):
            padding = "=" * ((8 - len(raw[1:]) % 8) % 8)
            decoded = base64.b32decode((raw[1:].upper() + padding).encode())
            version, offset = read_varint(decoded, 0)
            _, offset = read_varint(decoded, offset)
            algorithm, offset = read_varint(decoded, offset)
            length, offset = read_varint(decoded, offset)
            digest = decoded[offset : offset + length]
            return digest.hex() if version == 1 and algorithm == 0x12 and length == 32 and len(digest) == 32 else None
    except (ValueError, IndexError):
        return None
    return None


def base58_decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for character in value:
        position = alphabet.find(character)
        if position < 0:
            raise ValueError("invalid base58")
        number = number * 58 + position
    payload = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + payload


def read_varint(value: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(value):
        byte = value[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid varint")


def duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    state: dict[str, int] = {}
    stack: list[str] = []
    found: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in graph:
                continue
            if state.get(neighbor, 0) == 0:
                visit(neighbor)
            elif state.get(neighbor) == 1:
                start = stack.index(neighbor)
                body = stack[start:]
                rotations = [tuple(body[i:] + body[:i] + [body[i]]) for i in range(len(body))]
                found.add(min(rotations))
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node)
    return [list(value) for value in sorted(found)]


def normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def chosen_rejected(chosen: dict[str, Any], rejecting: dict[str, Any]) -> bool:
    statement = normalized(chosen.get("statement"))
    rejected = rejecting.get("rejected", [])
    return isinstance(rejected, list) and any(normalized(item) and normalized(item) in statement for item in rejected if isinstance(item, str))


def definition_term(entry: dict[str, Any]) -> str | None:
    if entry.get("kind") != "definition":
        return None
    question = normalized(entry.get("question"))
    if question:
        match = re.search(r"(?:what (?:is|does)|define)\s+(.+?)(?:\?|$)", question)
        if match:
            return match.group(1).strip(" `\"'")
    statement = normalized(entry.get("statement"))
    match = re.match(r"(.+?)\s+(?:means|is defined as|refers to)\s+", statement)
    return match.group(1).strip(" `\"'") if match else None


def git_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def resolve_roots(start: Path, explicit: str | None) -> tuple[Path, Path]:
    start = start.resolve()
    vcs_root = git_root(start)
    repo = vcs_root or start
    if explicit:
        root = Path(explicit)
        resolved = (root if root.is_absolute() else start / root).resolve()
        return resolved, repo
    current = start
    while True:
        config = current / "planning-config.json"
        if config.is_file():
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"cannot parse {config}: {exc}") from exc
            value = data.get("planningRoot", ".")
            if not isinstance(value, str):
                raise ValueError(f"{config}: planningRoot must be a string")
            root = Path(value)
            return (root if root.is_absolute() else current / root).resolve(), vcs_root or current
        if (vcs_root and current == vcs_root) or current.parent == current:
            return repo, repo
        current = current.parent


def path_matches_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def scope_root_for_artifact(artifact: Artifact) -> str:
    parts = Path(artifact.rel).parts
    if len(parts) >= 2 and parts[0] == "Plans":
        return f"Plans/{parts[1]}"
    return artifact.rel


def resolve_scope(
    validator: Validator,
    scope: str | None,
    diagnostics: Sequence[Diagnostic] = (),
) -> ScopeSelection:
    if not scope:
        all_paths = frozenset(artifact.rel for artifact in validator.artifacts)
        return ScopeSelection(all_paths, ())
    raw_value = scope.strip()
    raw_path = Path(raw_value)
    if raw_path.is_absolute() or "\\" in raw_value:
        return ScopeSelection(
            frozenset(),
            (),
            f"scope `{scope}` is unsafe; use a planning-root-relative artifact path without `.`, `..`, or backslashes",
        )
    value = raw_value.strip("/")
    if not value:
        return ScopeSelection(frozenset(), (), "scope is empty")
    path = Path(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        return ScopeSelection(
            frozenset(),
            (),
            f"scope `{scope}` is unsafe; use a planning-root-relative artifact path without `.`, `..`, or backslashes",
        )

    diagnostic_paths = {
        item.path
        for item in diagnostics
        if not item.path.startswith("@repo:") and not Path(item.path).is_absolute()
    }

    def has_diagnostic(root: str) -> bool:
        return any(path_matches_root(candidate, root) for candidate in diagnostic_paths)

    def recognized_artifact_path(candidate: str) -> bool:
        parts = Path(candidate).parts
        return bool(parts) and parts[0] in ARTIFACT_DIRS and candidate.endswith(".md")

    def root_for_unparsed(candidate: str) -> str:
        parts = Path(candidate).parts
        if len(parts) >= 2 and parts[0] == "Plans":
            return f"Plans/{parts[1]}"
        return candidate

    roots: list[str] = []
    physical_value = validator.root / value
    if physical_value.is_dir() and (
        any(path_matches_root(artifact.rel, value) for artifact in validator.artifacts)
        or has_diagnostic(value)
    ):
        roots = [value]
    direct = validator.resolve(value)
    if not roots and direct:
        roots = [scope_root_for_artifact(direct)]
    if not roots:
        explicit_roots = {
            artifact.rel
            for artifact in validator.artifacts
            if path_matches_root(artifact.rel, value)
        }
        if explicit_roots:
            roots = [value]
        else:
            physical_candidates = (value, f"{value}/README.md", f"{value}.md")
            physical = next(
                (
                    candidate
                    for candidate in physical_candidates
                    if recognized_artifact_path(candidate)
                    and (validator.root / candidate).is_file()
                    and has_diagnostic(candidate)
                ),
                None,
            )
            if physical:
                roots = [root_for_unparsed(physical)]
            else:
                historical = next(
                    (
                        candidate
                        for candidate in physical_candidates
                        if recognized_artifact_path(candidate)
                        and candidate in diagnostic_paths
                    ),
                    None,
                )
                if historical:
                    roots = [root_for_unparsed(historical)]
            if not roots and "/" not in value:
                aliases: list[str] = []
                for dirname in ARTIFACT_DIRS:
                    candidate = f"{dirname}/{value}"
                    resolved = validator.resolve(candidate)
                    if resolved:
                        aliases.append(scope_root_for_artifact(resolved))
                    elif any(
                        path_matches_root(artifact.rel, candidate)
                        for artifact in validator.artifacts
                    ):
                        aliases.append(candidate)
                    else:
                        alias_candidates = (candidate, f"{candidate}/README.md", f"{candidate}.md")
                        diagnostic_candidate = next(
                            (
                                path
                                for path in alias_candidates
                                if recognized_artifact_path(path)
                                and (
                                    path in diagnostic_paths
                                    or ((validator.root / path).is_file() and has_diagnostic(path))
                                )
                            ),
                            None,
                        )
                        if diagnostic_candidate:
                            aliases.append(root_for_unparsed(diagnostic_candidate))
                aliases = sorted(set(aliases))
                if len(aliases) > 1:
                    return ScopeSelection(
                        frozenset(),
                        tuple(aliases),
                        f"scope `{scope}` is ambiguous; use one of: {', '.join(aliases)}",
                    )
                if aliases:
                    roots = aliases
    if not roots:
        return ScopeSelection(frozenset(), (), f"scope `{scope}` does not resolve to an artifact")

    selected = {
        artifact.rel
        for artifact in validator.artifacts
        if any(path_matches_root(artifact.rel, root) for root in roots)
    }
    pending = list(selected)
    while pending:
        artifact = validator.by_path.get(pending.pop())
        if artifact is None:
            continue
        related = artifact.meta.get("related", [])
        if not isinstance(related, list):
            continue
        for reference in related:
            target = validator.resolve(reference) if isinstance(reference, str) else None
            if target and target.rel not in selected:
                target_root = scope_root_for_artifact(target)
                additions = {
                    candidate.rel
                    for candidate in validator.artifacts
                    if path_matches_root(candidate.rel, target_root)
                }
                for addition in additions - selected:
                    selected.add(addition)
                    pending.append(addition)
    return ScopeSelection(frozenset(selected), tuple(roots))


def select(
    diagnostics: list[Diagnostic],
    scope: str | None,
    artifacts_in_scope: set[str] | None = None,
    scope_roots: tuple[str, ...] | None = None,
    decision_paths: set[str] | None = None,
) -> list[Diagnostic]:
    if not scope:
        return diagnostics
    roots = scope_roots or (scope.strip().strip("/"),)

    def path_selected(path: str) -> bool:
        return (
            (artifacts_in_scope is not None and path in artifacts_in_scope)
            or any(path_matches_root(path, root) for root in roots)
        )

    return [
        item
        for item in diagnostics
        if item.severity == "operational"
        or item.code == "SDD000"
        or item.code.startswith("DLG")
        or item.path.startswith("@repo:")
        or item.path.startswith("Decisions/")
        or (decision_paths is not None and item.path in decision_paths)
        or path_selected(item.path)
        or any(path_selected(path) for path in item.implicated)
    ]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", help="Planning root; defaults through planning-config.json")
    result.add_argument("--scope", help="Limit findings to an artifact/path and its transitive explicit related-artifact graph")
    result.add_argument("--format", choices=("text", "json"), default="text", dest="output")
    result.add_argument("--identity-mode", choices=("auto", "current", "historical"), default="auto", help="Use current-worktree checks (auto/current) or validate historical durable objects only")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root, repo = resolve_roots(Path.cwd(), args.root)
    except ValueError as exc:
        print(f"sdd-validate: {exc}", file=sys.stderr)
        return 2
    validator = Validator(root, repo, args.identity_mode)
    all_diagnostics = validator.run()
    scope_selection = resolve_scope(validator, args.scope, all_diagnostics)
    operational_error = None
    if not validator.artifacts:
        operational_error = "planning root contains no discoverable SDD artifacts"
    elif scope_selection.error:
        operational_error = scope_selection.error
    if operational_error:
        if args.output == "json":
            print(json.dumps({"valid": False, "planning_root": str(root), "artifacts_inspected": len(validator.artifacts), "error": operational_error, "diagnostics": []}, indent=2, sort_keys=True))
        else:
            print(f"sdd-validate: {operational_error}", file=sys.stderr)
        return 2
    artifacts_in_scope = set(scope_selection.artifacts)
    diagnostics = select(
        all_diagnostics,
        args.scope,
        artifacts_in_scope,
        scope_selection.roots,
        {artifact.rel for artifact in validator.artifacts if artifact.kind == "decision-log"},
    )
    operational = [item for item in diagnostics if item.severity == "operational"]
    errors = [item for item in diagnostics if item.severity == "error"]
    if args.output == "json":
        print(json.dumps({"valid": not errors and not operational, "planning_root": str(root), "artifacts_inspected": len(validator.artifacts), "artifacts_in_scope": sorted(artifacts_in_scope), "diagnostics": [asdict(item) for item in diagnostics]}, indent=2, sort_keys=True))
    else:
        scope_summary = f", {len(artifacts_in_scope)} in scope" if args.scope else ""
        print(f"{'Valid' if not errors and not operational else 'Invalid'}: {root} ({len(validator.artifacts)} artifacts inspected{scope_summary})")
        for item in diagnostics:
            print(f"{item.severity.upper()} {item.code} {item.path}:{item.line}: {item.message}")
            print(f"  Required correction: {item.correction}")
        if not diagnostics:
            print("Checked structure, frontmatter, paths, identifiers, hierarchy, dependencies, reviews, decisions, and completion-evidence shape.")
    if operational:
        return 2
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
