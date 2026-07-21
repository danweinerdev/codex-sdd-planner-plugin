#!/usr/bin/env python3
"""Deterministically validate sdd-planner Markdown artifacts."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

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
        for artifact in self.artifacts:
            self._headings(artifact)
            self._references(artifact)
            self._specific(artifact)
            self._citations(artifact)
        self._graphs()
        self._traceability()
        self._decision_links()
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
        matches = list(re.finditer(rf"^{'#' * level}\s+(.+?)\s*$", artifact.body, re.MULTILINE))
        result: dict[str, tuple[int, str]] = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(artifact.body)
            line = artifact.body_line + artifact.body[: match.start()].count("\n")
            result[match.group(1).strip()] = (line, artifact.body[match.end() : end])
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
                if str(target.meta.get("phase", "")) != phase_id:
                    self.error(artifact, "SDD057", f"Phase `{phase_id}` disagrees with `{doc}` id `{target.meta.get('phase')}`.", "Make both ids identical.")
                if target.status != phase.get("status"):
                    self.error(artifact, "SDD058", f"Phase `{phase_id}` status disagrees with `{doc}`.", "Make both statuses identical.")
                if artifact.status == "complete" and target.status != "complete":
                    self.error(artifact, "SDD059", f"Complete plan contains incomplete phase `{phase_id}`.", "Complete every phase first.")
        for value in duplicates(ids):
            self.error(artifact, "SDD060", f"Duplicate phase id `{value}`.", "Assign a unique append-only phase id.")

    def _phase(self, artifact: Artifact) -> None:
        self._required(artifact, ("plan", "phase", "deliverable"))
        tasks = artifact.meta.get("tasks")
        if not isinstance(tasks, list):
            self.error(artifact, "SDD061", "`tasks` must be a list.", "Use `tasks: []` when empty.")
            return
        sections = self.sections(artifact)
        phase_id = str(artifact.meta.get("phase", ""))
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
            evidence = re.search(r"^###\s+Completion Evidence\s*$", body, re.MULTILINE)
            if evidence:
                remainder = body[evidence.end() :]
                following = re.search(r"^###\s+", remainder, re.MULTILINE)
                value = remainder[: following.start()] if following else remainder
                self._evidence(artifact, str(task.get("status", "")), f"Task {task_id} Completion Evidence", line + body[: evidence.start()].count("\n") + 1, value)
            if artifact.status == "complete" and task.get("status") != "complete":
                self.error(artifact, "SDD068", f"Complete phase contains incomplete task `{task_id}`.", "Complete every task first.")
        criteria = sections.get("Acceptance Criteria")
        if artifact.status == "complete" and criteria and re.search(r"^-\s*\[\s\]", criteria[1], re.MULTILINE):
            self.error(artifact, "SDD069", "Complete phase has unchecked acceptance criteria.", "Verify and check every criterion.", criteria[0])

    def _evidence(self, artifact: Artifact, status: str, name: str, line: int, body: str) -> None:
        pending = PENDING in body
        if status == "complete" and pending:
            self.error(artifact, "SDD070", f"Complete `{name}` is pending.", "Replace the marker with retrospective evidence.", line)
            return
        if pending:
            return
        labels = ("Verified", "Repository", "VCS", "Revision / base", "Evidence exclusions", "Governing intent", "Ignored inputs", "Directory inputs", "Identity recheck")
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
        exclusions = parse_exclusions(evidence_value(body, "Evidence exclusions"))
        governing = evidence_value(body, "Governing intent")
        snapshot = evidence_value(body, "Content snapshot")
        capture_paths = [location for value in (governing, snapshot) if value and (location := digest_location(value)) and not urlparse(location).scheme]
        self._check_exclusions(artifact, exclusions, capture_paths, name, line)
        recorded_inputs = parse_recorded_inputs(governing) if governing else set()
        required_inputs = self._required_intent_inputs(artifact)
        if governing and recorded_inputs != required_inputs:
            self.error(artifact, "SDD076", f"`{name}` governing inputs {sorted(recorded_inputs)} do not match required inputs {sorted(required_inputs)}.", "Regenerate the projection from the plan, governing phase(s), related specs/designs, and cited accepted decisions.", line)
        if vcs in {"git", "git-worktree"} and revision and not revision.endswith("-dirty"):
            compare_current = self.identity_mode != "historical"
            self._verify_clean_git_identity(artifact, revision, exclusions, name, line, compare_current)
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
        if revision.endswith("-dirty") or vcs in {"perforce", "none"}:
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
                )
            else:
                self.error(artifact, "SDD074", f"`{name}` requires a content snapshot.", "Record its SHA-256 and durable manifest path.", line)
        recheck = evidence_value(body, "Identity recheck") or ""
        if recheck and (
            not re.search(r"\bmatch(?:ed|es|ing)?\b", recheck, re.IGNORECASE)
            or not re.search(r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d", recheck)
        ):
            self.error(artifact, "SDD075", f"`{name}` recheck lacks a timestamped matching result.", "Record the exact tool, ISO timestamp, and matching identity.", line)

    def _verify_clean_git_identity(self, artifact: Artifact, revision: str, exclusions: set[str], name: str, line: int, compare_current: bool) -> None:
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
        changed: set[str] = set()
        for args in (("diff", "--name-only", "-z", revision, "--"), ("diff", "--cached", "--name-only", "-z", revision, "--"), ("ls-files", "--others", "--exclude-standard", "-z")):
            result = git(*args)
            if result.returncode != 0:
                self.error(artifact, "SDD072", f"`{name}` current Git identity check failed: {result.stderr.decode(errors='replace').strip()}", "Repair the worktree or rerun validation with the correct repository.", line)
                return
            changed.update(item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item)
        unexpected = sorted(changed - exclusions)
        if unexpected:
            self.error(artifact, "SDD072", f"`{name}` current worktree differs from `{revision}` at: {', '.join(unexpected)}.", "Re-run verification at the recorded identity or capture a canonical dirty snapshot.", line)

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
            if entry.get("decided_by") not in {"user", "user-approved"}:
                self.error(artifact, "SDD117", f"Decision `{decision_id}` has invalid `decided_by`.", "Use user or user-approved.")

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
                    self.error(artifact, "SDD147", f"`{left_id}` and `{right_id}` answer the same question differently.", "Ask the user to reconcile or separate scopes.")
                if chosen_rejected(left, right) or chosen_rejected(right, left):
                    self.error(artifact, "SDD148", f"`{left_id}` and `{right_id}` choose and reject the same option.", "Ask the user to reconcile the collision.")
                left_term = definition_term(left)
                right_term = definition_term(right)
                if left_term and left_term == right_term and normalized(left.get("statement")) != normalized(right.get("statement")):
                    self.error(artifact, "SDD149", f"`{left_id}` and `{right_id}` define `{left_term}` differently.", "Ask the user to reconcile the definitions or separate their scopes.")

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
    for raw_line in body.splitlines():
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
    return re.fullmatch(r"(?:[A-Za-z0-9._/-]|%[0-9A-F]{2})+", value) is not None


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


def select(diagnostics: list[Diagnostic], scope: str | None) -> list[Diagnostic]:
    if not scope:
        return diagnostics
    value = scope.strip().strip("/")
    prefixes = (value, f"Plans/{value}", f"Specs/{value}", f"Designs/{value}")
    return [
        item
        for item in diagnostics
        if item.code == "SDD000"
        or item.path.startswith("@repo:")
        or any(item.path == prefix or item.path.startswith(prefix + "/") for prefix in prefixes)
        or any(any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes) for path in item.implicated)
    ]


def scope_resolves(artifacts: list[Artifact], scope: str) -> bool:
    value = scope.strip().strip("/")
    prefixes = (value, f"Plans/{value}", f"Specs/{value}", f"Designs/{value}")
    return any(any(item.rel == prefix or item.rel.startswith(prefix + "/") for prefix in prefixes) for item in artifacts)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", help="Planning root; defaults through planning-config.json")
    result.add_argument("--scope", help="Limit reported findings to a path or artifact name")
    result.add_argument("--format", choices=("text", "json"), default="text", dest="output")
    result.add_argument("--identity-mode", choices=("auto", "current", "historical"), default="auto", help="Compare recorded identities to the current worktree, historical objects only, or infer from completion status")
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
    operational_error = None
    if not validator.artifacts:
        operational_error = "planning root contains no discoverable SDD artifacts"
    elif args.scope and not scope_resolves(validator.artifacts, args.scope):
        operational_error = f"scope `{args.scope}` does not resolve to an artifact"
    if operational_error:
        if args.output == "json":
            print(json.dumps({"valid": False, "planning_root": str(root), "artifacts_inspected": len(validator.artifacts), "error": operational_error, "diagnostics": []}, indent=2, sort_keys=True))
        else:
            print(f"sdd-validate: {operational_error}", file=sys.stderr)
        return 2
    diagnostics = select(all_diagnostics, args.scope)
    if args.output == "json":
        print(json.dumps({"valid": not diagnostics, "planning_root": str(root), "artifacts_inspected": len(validator.artifacts), "diagnostics": [asdict(item) for item in diagnostics]}, indent=2, sort_keys=True))
    else:
        print(f"{'Valid' if not diagnostics else 'Invalid'}: {root} ({len(validator.artifacts)} artifacts inspected)")
        for item in diagnostics:
            print(f"{item.severity.upper()} {item.code} {item.path}:{item.line}: {item.message}")
            print(f"  Required correction: {item.correction}")
        if not diagnostics:
            print("Checked structure, frontmatter, paths, identifiers, hierarchy, dependencies, reviews, decisions, and completion-evidence shape.")
    return 0 if not diagnostics else 1


if __name__ == "__main__":
    raise SystemExit(main())
