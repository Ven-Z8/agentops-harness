from __future__ import annotations

import math
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"
    DONE = "done"


class EvidenceState(StrEnum):
    MISSING = "missing"
    INCONCLUSIVE = "inconclusive"
    PARTIAL = "partial"
    VERIFIED = "verified"


class VerificationState(StrEnum):
    NOT_RUN = "not_run"
    PARTIAL = "partial"
    FAILED = "failed"
    PASSED = "passed"


def _nonempty(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty")
    return value


def _single_line_identifier(value: str) -> str:
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(
            "must be a single-line identifier using letters, digits, dots, underscores, or hyphens"
        )
    return value


def _single_line_text(value: str) -> str:
    _nonempty(value)
    if any(
        ord(character) < 32 or ord(character) == 127 or character in {"\u0085", "\u2028", "\u2029"}
        for character in value
    ):
        raise ValueError("must be non-empty single-line text without control characters")
    return value


def _https_url(value: str) -> str:
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValueError("URL must be a single line without control characters or whitespace")
    if any(character in value for character in '<>"'):
        raise ValueError("URL contains unsafe Markdown destination syntax")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError("URL must have valid syntax") from error
    if parsed.scheme != "https" or not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must be an absolute https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")
    return value


def _relative_repository_path(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("repository path must be a non-empty normalized relative path")
    directory_marker = value.endswith("/")
    normalized_value = value[:-1] if directory_marker else value
    path = PurePosixPath(normalized_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("repository path must be normalized and remain inside the worktree")
    if str(path) != normalized_value:
        raise ValueError("repository path must be normalized")
    return value


def _safe_relative_link_target(value: str) -> str:
    """Validate a normalized repository path before placing it in a Markdown link."""
    if not value or not value.isascii():
        raise ValueError("link target must use non-empty ASCII path segments")
    segments = value.split("/")
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+", segment) for segment in segments):
        raise ValueError("link target must use only safe ASCII repository path segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("link target must not contain dot path segments")
    return value


def _relative_repository_paths(values: list[str]) -> list[str]:
    return [_relative_repository_path(value) for value in values]


def _nonempty_text_list(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("must not be empty")
    return [_nonempty(value) for value in values]


class ProjectIdentity(StrictModel):
    id: str
    name: str
    repository: str
    default_branch: str

    _validate_strings = field_validator("id", "name", "repository", "default_branch")(_nonempty)


class RoadmapConfig(StrictModel):
    id: str
    source: str

    _validate_id = field_validator("id")(_single_line_identifier)
    _validate_source = field_validator("source")(_relative_repository_path)


class GitHubProjectConfig(StrictModel):
    owner: str
    number: int | None
    url: str | None

    _validate_owner = field_validator("owner")(_nonempty)

    @model_validator(mode="after")
    def require_number_and_url_together(self) -> GitHubProjectConfig:
        if (self.number is None) != (self.url is None):
            raise ValueError("GitHub project number and url must be populated together")
        if self.number is not None and self.number < 1:
            raise ValueError("GitHub project number must be positive")
        if self.url is not None:
            _https_url(self.url)
        return self


class GeneratedPaths(StrictModel):
    board: str
    current: str
    codegraph: str

    _validate_paths = field_validator("board", "current", "codegraph")(_relative_repository_path)


class ProjectConfig(StrictModel):
    schema_version: Literal[1]
    project: ProjectIdentity
    roadmap: RoadmapConfig
    github_project: GitHubProjectConfig
    generated: GeneratedPaths

    @model_validator(mode="after")
    def validate_generated_output_layout(self) -> ProjectConfig:
        if self.generated.current != "coordination/CURRENT.md":
            raise ValueError("generated current path must be coordination/CURRENT.md")
        if self.generated.board != "coordination/BOARD.md":
            raise ValueError("generated board path must be coordination/BOARD.md")

        generated = {
            "board": PurePosixPath(self.generated.board),
            "current": PurePosixPath(self.generated.current),
            "codegraph": PurePosixPath(self.generated.codegraph),
        }
        coordination = PurePosixPath("coordination")
        for name, path in generated.items():
            if path == coordination or not path.is_relative_to(coordination):
                raise ValueError(
                    f"generated {name} path must be contained in the coordination output surface"
                )

        names = list(generated)
        for index, first_name in enumerate(names):
            first = generated[first_name]
            for second_name in names[index + 1 :]:
                second = generated[second_name]
                if first == second or first.is_relative_to(second) or second.is_relative_to(first):
                    raise ValueError(
                        f"generated {first_name} and {second_name} paths must be distinct "
                        "and non-overlapping"
                    )

        roadmap = PurePosixPath(self.roadmap.source)
        protected_surfaces = {
            PurePosixPath("app"),
            PurePosixPath("src"),
            PurePosixPath("source"),
            PurePosixPath("tests"),
            PurePosixPath("scripts"),
            PurePosixPath("coordination/project.yaml"),
            PurePosixPath("coordination/README.md"),
            PurePosixPath("coordination/PROJECT.md"),
            PurePosixPath("coordination/roadmap"),
            roadmap,
            roadmap.parent,
            *(
                coordination / name
                for name in (
                    "artifacts",
                    "decisions",
                    "designs",
                    "handoffs",
                    "plans",
                    "templates",
                )
            ),
        }
        for name, output in generated.items():
            for protected in protected_surfaces:
                overlaps = (
                    output == protected
                    or output.is_relative_to(protected)
                    or protected.is_relative_to(output)
                )
                if overlaps:
                    raise ValueError(
                        f"generated {name} path overlaps protected input surface {protected}"
                    )
        return self


class GitHubIssueReference(StrictModel):
    issue_number: int | None
    issue_url: str | None

    @model_validator(mode="after")
    def require_number_and_url_together(self) -> GitHubIssueReference:
        if (self.issue_number is None) != (self.issue_url is None):
            raise ValueError("GitHub issue number and url must be populated together")
        if self.issue_number is not None and self.issue_number < 1:
            raise ValueError("GitHub issue number must be positive")
        if self.issue_url is not None:
            _https_url(self.issue_url)
        return self


class RoadmapItem(StrictModel):
    id: str
    title: str
    kind: Literal["roadmap", "phase", "outcome", "task", "decision", "research"]
    day: int | None = None
    phase_id: str | None = None
    parent_id: str | None = None
    status: ProjectStatus
    maturity: Literal["confirmed", "needs-revalidation"]
    priority: Literal["P0", "P1", "P2", "P3"]
    risk: Literal["critical", "high", "medium", "low"]
    blocker: str
    outcome: str
    scope: list[str]
    non_goals: list[str]
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    required_evidence: list[str]
    likely_files: list[str]
    test_first: str | None
    terminal_semantics: str
    compatibility: str
    verification_commands: list[str]
    verification_readiness: Literal["planned", "available"]
    risks: list[str]
    rollback: str
    source_documents: list[str]
    github: GitHubIssueReference

    _validate_id = field_validator("id")(_single_line_identifier)
    _validate_text = field_validator(
        "title",
        "blocker",
        "outcome",
        "terminal_semantics",
        "compatibility",
        "rollback",
    )(_nonempty)
    _validate_required_text_lists = field_validator(
        "scope",
        "non_goals",
        "acceptance_criteria",
        "required_evidence",
        "verification_commands",
        "risks",
        "source_documents",
    )(_nonempty_text_list)
    _validate_repository_paths = field_validator("likely_files", "source_documents")(
        _relative_repository_paths
    )

    @field_validator("parent_id", "phase_id")
    @classmethod
    def validate_optional_reference(cls, value: str | None) -> str | None:
        return None if value is None else _single_line_identifier(value)

    @field_validator("dependencies")
    @classmethod
    def validate_dependency_references(cls, values: list[str]) -> list[str]:
        return [_single_line_identifier(value) for value in values]

    @field_validator("test_first")
    @classmethod
    def validate_test_first(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value)

    @field_validator("day")
    @classmethod
    def validate_day(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 14:
            raise ValueError("day must be between 1 and 14")
        return value

    @model_validator(mode="after")
    def validate_task_only_fields(self) -> RoadmapItem:
        if self.kind == "task":
            if self.test_first is None:
                raise ValueError("task requires a non-null test_first")
            if not self.likely_files:
                raise ValueError("task requires non-empty likely_files")
        elif self.test_first is not None or self.likely_files:
            raise ValueError("non-task records reject task-only fields")
        return self


class Roadmap(StrictModel):
    schema_version: Literal[1]
    roadmap_id: str = Field(min_length=1)
    items: list[RoadmapItem] = Field(min_length=1)

    _validate_roadmap_id = field_validator("roadmap_id")(_single_line_identifier)

    @model_validator(mode="after")
    def validate_dependencies(self) -> Roadmap:
        identifiers = [item.id for item in self.items]
        duplicate_ids = {item_id for item_id in identifiers if identifiers.count(item_id) > 1}
        if duplicate_ids:
            raise ValueError(f"duplicate roadmap item IDs: {sorted(duplicate_ids)}")
        known_ids = set(identifiers)
        dependencies = {item.id: item.dependencies for item in self.items}
        for item_id, item_dependencies in dependencies.items():
            for dependency in item_dependencies:
                if dependency == item_id:
                    raise ValueError(f"self-dependency for roadmap item: {item_id}")
                if dependency not in known_ids:
                    raise ValueError(
                        f"unknown dependency {dependency!r} for roadmap item {item_id}"
                    )

        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(item_id: str) -> None:
            if item_id in visiting:
                raise ValueError(f"dependency cycle includes roadmap item: {item_id}")
            if item_id in visited:
                return
            visiting.add(item_id)
            for dependency in dependencies[item_id]:
                visit(dependency)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in identifiers:
            visit(item_id)
        return self


class HandoffVerification(StrictModel):
    required: bool = False
    state: VerificationState
    commands: list[str] = Field(default_factory=list)


class HandoffHeader(StrictModel):
    schema_version: Literal[1]
    task_id: str
    harness: str
    status: Literal["completed", "partial", "blocked", "abandoned"]
    started_at: datetime
    updated_at: datetime
    branch: str
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification: HandoffVerification
    artifacts: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blocker: str | None = None
    required_authority: str | None = None

    _validate_identifiers = field_validator("task_id", "harness")(_single_line_identifier)
    _validate_branch = field_validator("branch")(_single_line_text)

    @model_validator(mode="after")
    def enforce_terminal_semantics(self) -> HandoffHeader:
        if self.updated_at < self.started_at:
            raise ValueError("updated_at must not precede started_at")
        if (
            self.status == "completed"
            and self.verification.required
            and self.verification.state is not VerificationState.PASSED
        ):
            raise ValueError("completed handoff with required verification must be passed")
        if self.status == "blocked":
            if not self.blocker or not self.blocker.strip():
                raise ValueError("blocked handoff requires blocker")
            if not self.required_authority or not self.required_authority.strip():
                raise ValueError("blocked handoff requires required_authority")
        return self


class DecisionHeader(StrictModel):
    schema_version: Literal[1]
    decision_id: str
    status: Literal["proposed", "accepted", "superseded", "rejected"]
    date: datetime
    owners: list[str] = Field(min_length=1)
    task_ids: list[str] = Field(min_length=1)
    superseding_decision_id: str | None = None

    _validate_id = field_validator("decision_id")(_nonempty)

    @model_validator(mode="after")
    def validate_supersession(self) -> DecisionHeader:
        if self.status == "superseded" and not self.superseding_decision_id:
            raise ValueError("superseded decision requires superseding_decision_id")
        if self.status != "superseded" and self.superseding_decision_id is not None:
            raise ValueError("only superseded decisions may name a superseding decision")
        if self.superseding_decision_id == self.decision_id:
            raise ValueError("decision cannot supersede itself")
        return self


class ArtifactRecord(StrictModel):
    id: str
    task_id: str
    kind: str
    availability: Literal["repository", "local", "remote", "unavailable"]
    locator: str | None
    sha256: str | None = None
    required: bool = False
    evidence_state: EvidenceState = EvidenceState.MISSING
    created_at: datetime
    producer: str
    immutable: bool = False

    _validate_text = field_validator("id", "task_id", "kind", "producer")(_nonempty)

    @model_validator(mode="after")
    def validate_evidence(self) -> ArtifactRecord:
        if self.availability == "unavailable":
            if self.locator is not None:
                raise ValueError("unavailable artifact must not have a locator")
            if self.evidence_state is EvidenceState.VERIFIED:
                raise ValueError("unavailable artifact cannot claim verified evidence")
        else:
            if not self.locator or not self.locator.strip():
                raise ValueError("available artifact requires a locator")
        if (
            self.availability == "remote"
            and self.locator
            and not self.locator.startswith("https://")
        ):
            raise ValueError("remote artifact requires a durable https locator")
        if self.availability == "repository" and self.locator:
            _relative_repository_path(self.locator)
        if self.immutable and self.availability in {"repository", "remote"} and not self.sha256:
            raise ValueError("immutable external evidence requires sha256")
        return self


class ArtifactIndex(StrictModel):
    schema_version: Literal[1]
    artifacts: list[ArtifactRecord]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ArtifactIndex:
        identifiers = [artifact.id for artifact in self.artifacts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate artifact IDs")
        return self


class GraphManifest(StrictModel):
    schema_version: Literal[1]
    generator_version: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    included_paths: list[str]
    exclusions: list[str]
    counts: dict[str, int]
    generated_at: datetime
    language_coverage: dict[str, list[str]]

    _validate_included_paths = field_validator("included_paths")(_relative_repository_paths)


class BoardItem(StrictModel):
    task_id: str
    title: str
    status: ProjectStatus
    priority: Literal["P0", "P1", "P2", "P3"]
    day: int | None = None
    phase_id: str | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    evidence: EvidenceState = EvidenceState.MISSING
    harness: str | None = None
    dependency: str | None = None
    blocker: str | None = None
    handoff: str | None = None

    _validate_task_id = field_validator("task_id")(_single_line_identifier)
    _validate_title = field_validator("title")(_nonempty)
    _validate_optional_identifiers = field_validator("phase_id", "harness")(
        lambda value: None if value is None else _single_line_identifier(value)
    )
    _validate_handoff = field_validator("handoff")(
        lambda value: (
            None
            if value is None
            else _https_url(value)
            if value.startswith("https://")
            else _safe_relative_link_target(value)
        )
    )

    @field_validator("day")
    @classmethod
    def validate_day(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 14:
            raise ValueError("day must be between 1 and 14")
        return value

    @model_validator(mode="after")
    def require_issue_reference_parts_together(self) -> BoardItem:
        if (self.issue_number is None) != (self.issue_url is None):
            raise ValueError("Board issue number and url must be populated together")
        if self.issue_number is not None and self.issue_number < 1:
            raise ValueError("Board issue number must be positive")
        if self.issue_url is not None:
            _https_url(self.issue_url)
        return self


class BoardExport(StrictModel):
    project_url: str
    items: list[BoardItem]
    repository: str | None = None
    source_revision: str = "unavailable"

    @field_validator("project_url")
    @classmethod
    def validate_project_url(cls, value: str) -> str:
        return _https_url(value)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("Board repository must be a canonical owner/name")
        return value

    @field_validator("source_revision")
    @classmethod
    def validate_source_revision(cls, value: str) -> str:
        if value != "unavailable" and not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Board source revision must be a full commit SHA or unavailable")
        return value


class ControlRoomState(StrictModel):
    project: ProjectConfig
    roadmap: Roadmap
    artifacts: ArtifactIndex | None = None
    graph_manifest: GraphManifest | None = None
    board_export: BoardExport | None = None
    handoffs: dict[str, HandoffHeader] = Field(default_factory=dict)
    decisions: dict[str, DecisionHeader] = Field(default_factory=dict)
    handoff_paths: dict[str, str] = Field(default_factory=dict)
    decision_paths: dict[str, str] = Field(default_factory=dict)
    approved_baseline: Literal["39c041f699d7909d1f6853a89bf2a86835a4acd4"] = (
        "39c041f699d7909d1f6853a89bf2a86835a4acd4"
    )
    snapshot_source_revision: str = "unavailable"

    @field_validator("snapshot_source_revision")
    @classmethod
    def validate_snapshot_source_revision(cls, value: str) -> str:
        if value != "unavailable" and not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Snapshot source revision must be a full commit SHA or unavailable")
        return value


# GitHub provisioning is deliberately represented separately from BoardExport.  BoardExport
# is the validated read-only snapshot consumed by local renderers; these records are the
# minimum remote identity needed by the deterministic provisioning planner.
class RemoteProject(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    number: int = Field(gt=0)
    name: str = Field(min_length=1)
    url: str

    _validate_url = field_validator("url")(_https_url)
    _validate_name = field_validator("name")(_single_line_text)


class RemoteIssue(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    task_id: str = Field(min_length=1, pattern=r"^AO-(?:14D|P[1-6]|D\d{2}(?:-\d{2})?)$")
    node_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    number: int = Field(gt=0)
    url: str
    title: str | None = None
    body: str = ""

    _validate_url = field_validator("url")(_https_url)
    _validate_title = field_validator("title")(_single_line_text)


class RemoteOption(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    name: str = Field(min_length=1)

    _validate_name = field_validator("name")(_single_line_text)


class RemoteFieldValue(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    field_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    field_type: Literal["single-select", "text", "number", "date"]
    option_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_:-]+$")
    option_name: str | None = Field(default=None, min_length=1)
    text: str | None = None
    number: int | float | None = None
    date: str | None = None

    @model_validator(mode="after")
    def validate_typed_value(self) -> RemoteFieldValue:
        if isinstance(self.number, bool):
            raise ValueError("remote number field value must not be boolean")
        if self.number is not None and not math.isfinite(self.number):
            raise ValueError("remote number field value must be finite")
        if self.field_type == "single-select" and (
            self.option_id is None or self.option_name is None
        ):
            raise ValueError("remote single-select value requires option ID and name")
        populated = {
            "single-select": (self.option_id, self.option_name),
            "text": (self.text,),
            "number": (self.number,),
            "date": (self.date,),
        }[self.field_type]
        other_values = {
            "single-select": (self.text, self.number, self.date),
            "text": (self.option_id, self.option_name, self.number, self.date),
            "number": (self.option_id, self.option_name, self.text, self.date),
            "date": (self.option_id, self.option_name, self.text, self.number),
        }[self.field_type]
        if not any(value is not None for value in populated) or any(
            value is not None for value in other_values
        ):
            raise ValueError("remote field value has exactly one typed value")
        return self

    @field_validator("text", "option_name")
    @classmethod
    def validate_safe_text(cls, value: str | None) -> str | None:
        if value is not None:
            _single_line_text(value)
        return value

    @field_validator("date")
    @classmethod
    def validate_iso_date(cls, value: str | None) -> str | None:
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("remote date must use ISO YYYY-MM-DD")
            from datetime import date

            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("remote date is not calendar-valid") from error
        return value

    @property
    def value(self) -> str | int | float | None:
        if self.field_type == "single-select":
            return self.option_name or self.option_id
        if self.field_type == "text":
            return self.text
        if self.field_type == "number":
            return self.number
        return self.date


class RemoteField(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    name: str = Field(min_length=1)
    data_type: str | None = None
    options: tuple[RemoteOption, ...] = ()

    @field_validator("options", mode="before")
    @classmethod
    def freeze_options(cls, value: object) -> object:
        return tuple(value) if isinstance(value, (list, tuple)) else value


class RemoteProjectItem(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    task_id: str = Field(min_length=1, pattern=r"^AO-(?:14D|P[1-6]|D\d{2}(?:-\d{2})?)$")
    content_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_:-]+$")
    issue_number: int | None = Field(default=None, gt=0)
    issue_url: str | None = None
    issue_title: str | None = None
    field_values: tuple[RemoteFieldValue, ...] = ()

    _validate_issue_url = field_validator("issue_url")(_https_url)
    _validate_issue_title = field_validator("issue_title")(_single_line_text)

    @field_validator("field_values", mode="before")
    @classmethod
    def freeze_field_values(cls, value: object) -> object:
        if isinstance(value, dict):
            return tuple(value.values())
        return tuple(value) if isinstance(value, (list, tuple)) else value

    @model_validator(mode="after")
    def reject_duplicate_fields(self) -> RemoteProjectItem:
        field_ids = [value.field_id for value in self.field_values]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("duplicate field value for remote field ID")
        return self


class RemoteView(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")
    name: str = Field(min_length=1)
    layout: str | None = None
    group_by: str | None = None
    sort_by: str | None = None
    filter: str | None = None


class RemoteGitHubState(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    owner: str = Field(min_length=1)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    owner_id: str | None = None
    repository_id: str | None = None
    project: RemoteProject | None = None
    issues: tuple[RemoteIssue, ...] = ()
    fields: tuple[RemoteField, ...] = ()
    items: tuple[RemoteProjectItem, ...] = ()
    views: tuple[RemoteView, ...] = ()

    @field_validator("issues", "fields", "items", "views", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, (list, tuple)) else value

    @field_validator("owner_id", "repository_id")
    @classmethod
    def validate_remote_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"^[A-Za-z0-9_:-]+$", value):
            raise ValueError("remote ID must be a safe single-line identifier")
        return value

    @model_validator(mode="after")
    def validate_unique_remote_keys(self) -> RemoteGitHubState:
        issue_ids = [issue.task_id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("duplicate remote issue stable task ID")
        for issue in self.issues:
            expected = f"https://github.com/{self.repository}/issues/{issue.number}"
            if issue.url != expected:
                raise ValueError("remote issue URL does not match configured repository")
        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("duplicate remote field name")
        for field in self.fields:
            if len(field.options) != len({option.id for option in field.options}):
                raise ValueError(f"duplicate options for remote field: {field.name}")
            if len(field.options) != len({option.name for option in field.options}):
                raise ValueError(f"duplicate option names for remote field: {field.name}")
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate remote project item ID")
        item_tasks = [item.task_id for item in self.items]
        if len(item_tasks) != len(set(item_tasks)):
            raise ValueError("duplicate remote project item stable task ID")
        if not set(item_tasks).issubset(set(issue_ids)):
            raise ValueError("remote project item references unknown issue stable task ID")
        field_ids = {field.id for field in self.fields}
        for item in self.items:
            if not {value.field_id for value in item.field_values}.issubset(field_ids):
                raise ValueError("remote field value references unknown field ID")
        view_names = [view.name for view in self.views]
        if len(view_names) != len(set(view_names)):
            raise ValueError("duplicate remote view name")
        all_node_ids = [
            *([self.project.id] if self.project is not None else []),
            *[issue.node_id for issue in self.issues],
            *[field.id for field in self.fields],
            *[option.id for field in self.fields for option in field.options],
            *[item.id for item in self.items],
            *[value.id for item in self.items for value in item.field_values],
            *[view.id for view in self.views],
        ]
        if len(all_node_ids) != len(set(all_node_ids)):
            raise ValueError("duplicate remote GitHub node ID")
        return self


ProvisionResource = Literal["project", "field", "view", "issue", "item", "field-value"]
ProvisionActionKind = Literal["create", "reuse", "update"]


@dataclass(frozen=True)
class ProvisionAction:
    resource: ProvisionResource
    stable_key: str
    action: ProvisionActionKind
    remote_id: str | None
    payload: dict[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        # Dataclass freezing only protects attribute rebinding.  Freeze nested
        # payloads too, since action payloads are the durable mutation plan.
        object.__setattr__(self, "payload", _freeze_plan_value(self.payload))

    def as_dict(self) -> dict[str, object]:
        return {
            "resource": self.resource,
            "stable_key": self.stable_key,
            "action": self.action,
            "remote_id": self.remote_id,
            "payload": _thaw_plan_value(self.payload),
        }


@dataclass(frozen=True)
class ProvisioningPlan:
    project: ProvisionAction
    field_actions: tuple[ProvisionAction, ...] = ()
    issue_actions: tuple[ProvisionAction, ...] = ()
    item_actions: tuple[ProvisionAction, ...] = ()
    field_value_actions: tuple[ProvisionAction, ...] = ()
    view_actions: tuple[ProvisionAction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "project", self.project)
        for name in (
            "field_actions",
            "issue_actions",
            "item_actions",
            "field_value_actions",
            "view_actions",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def actions(self) -> tuple[ProvisionAction, ...]:
        return (
            self.project,
            *sorted(self.field_actions, key=lambda action: action.stable_key),
            *sorted(self.issue_actions, key=lambda action: action.stable_key),
            *sorted(self.item_actions, key=lambda action: action.stable_key),
            *sorted(self.field_value_actions, key=lambda action: action.stable_key),
            *sorted(self.view_actions, key=lambda action: action.stable_key),
        )

    def as_dict(self) -> dict[str, object]:
        return {"actions": [action.as_dict() for action in self.actions]}

    def to_json(self) -> str:
        import json

        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# GitHub Provisioning Plan",
            "",
            "| Resource | Stable key | Action | Remote ID |",
            "| --- | --- | --- | --- |",
        ]
        for action in self.actions:
            lines.append(
                "| "
                f"{action.resource} | {action.stable_key} | {action.action} | "
                f"{action.remote_id or '—'} |"
            )
        return "\n".join(lines) + "\n"


class ReconciliationAction(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    resource: ProvisionResource
    stable_key: str = Field(min_length=1)
    action: ProvisionActionKind
    remote_id: str | None = None
    payload: tuple[tuple[str, object], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def freeze_payload(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("payload"), dict):
            value = dict(value)
            value["payload"] = tuple(
                (key, _freeze_report_value(item)) for key, item in sorted(value["payload"].items())
            )
        return value


class ReconciliationId(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    stable_key: str = Field(min_length=1)
    remote_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_:-]+$")


class ReconciliationReport(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    state: Literal["success", "partial"]
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_object_ids: tuple[ReconciliationId, ...] = ()
    attempted_actions: tuple[ReconciliationAction, ...] = ()
    completed_actions: tuple[ReconciliationAction, ...] = ()
    remaining_actions: tuple[ReconciliationAction, ...] = ()
    skipped_actions: tuple[ReconciliationAction, ...] = ()
    manual_instructions: tuple[str, ...] = ()
    error: str | None = None
    report_path: str | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> ReconciliationReport:
        if self.updated_at < self.started_at:
            raise ValueError("reconciliation updated_at must not precede started_at")
        return self

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_object_ids": {
                item.stable_key: item.remote_id for item in self.completed_object_ids
            },
            "attempted_actions": [_report_action_dict(action) for action in self.attempted_actions],
            "completed_actions": [_report_action_dict(action) for action in self.completed_actions],
            "remaining_actions": [_report_action_dict(action) for action in self.remaining_actions],
            "skipped_actions": [_report_action_dict(action) for action in self.skipped_actions],
            "manual_instructions": list(self.manual_instructions),
            "error": self.error,
            "report_path": self.report_path,
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _report_action_dict(action: ReconciliationAction) -> dict[str, object]:
    return {
        "resource": action.resource,
        "stable_key": action.stable_key,
        "action": action.action,
        "remote_id": action.remote_id,
        "payload": {key: _thaw_report_value(value) for key, value in action.payload},
    }


def _freeze_report_value(value: object) -> object:
    if isinstance(value, dict):
        return tuple((str(key), _freeze_report_value(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_report_value(item) for item in value)
    return value


def _freeze_plan_value(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_plan_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_plan_value(item) for item in value)
    return value


def _thaw_plan_value(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {key: _thaw_plan_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_plan_value(item) for item in value]
    return value


def _thaw_report_value(value: object) -> object:
    if isinstance(value, tuple):
        if value and all(
            isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
            for item in value
        ):
            return {key: _thaw_report_value(item) for key, item in value}
        return [_thaw_report_value(item) for item in value]
    return value
