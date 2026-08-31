from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

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


def _relative_repository_path(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("repository path must be a non-empty normalized relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("repository path must be normalized and remain inside the worktree")
    if str(path) != value:
        raise ValueError("repository path must be normalized")
    return value


def _relative_repository_paths(values: list[str]) -> list[str]:
    return [_relative_repository_path(value) for value in values]


class ProjectIdentity(StrictModel):
    id: str
    name: str
    repository: str
    default_branch: str

    _validate_strings = field_validator("id", "name", "repository", "default_branch")(_nonempty)


class RoadmapConfig(StrictModel):
    id: str
    source: str

    _validate_id = field_validator("id")(_nonempty)
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
        if self.url is not None and not self.url.startswith("https://"):
            raise ValueError("GitHub project url must be an https URL")
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


class GitHubIssueReference(StrictModel):
    issue_number: int | None
    issue_url: str | None

    @model_validator(mode="after")
    def require_number_and_url_together(self) -> GitHubIssueReference:
        if (self.issue_number is None) != (self.issue_url is None):
            raise ValueError("GitHub issue number and url must be populated together")
        if self.issue_number is not None and self.issue_number < 1:
            raise ValueError("GitHub issue number must be positive")
        if self.issue_url is not None and not self.issue_url.startswith("https://"):
            raise ValueError("GitHub issue url must be an https URL")
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
    test_first: str
    terminal_semantics: str
    compatibility: str
    verification_commands: list[str]
    risks: list[str]
    rollback: str
    source_documents: list[str]
    github: GitHubIssueReference

    _validate_id_and_text = field_validator(
        "id",
        "title",
        "blocker",
        "outcome",
        "test_first",
        "terminal_semantics",
        "compatibility",
        "rollback",
    )(_nonempty)
    _validate_repository_paths = field_validator("likely_files", "source_documents")(
        _relative_repository_paths
    )

    @field_validator("day")
    @classmethod
    def validate_day(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 14:
            raise ValueError("day must be between 1 and 14")
        return value


class Roadmap(StrictModel):
    schema_version: Literal[1]
    roadmap_id: str = Field(min_length=1)
    items: list[RoadmapItem] = Field(min_length=1)

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

    _validate_text = field_validator("task_id", "harness", "branch")(_nonempty)

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
        if self.availability == "remote" and self.locator and not self.locator.startswith("https://"):
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
    handoff: str | None = None


class BoardExport(StrictModel):
    project_url: str
    items: list[BoardItem]
    source_revision: str | None = None


class ControlRoomState(StrictModel):
    project: ProjectConfig
    roadmap: Roadmap
    artifacts: ArtifactIndex | None = None
    graph_manifest: GraphManifest | None = None
    board_export: BoardExport | None = None
    handoffs: dict[str, HandoffHeader] = Field(default_factory=dict)
    decisions: dict[str, DecisionHeader] = Field(default_factory=dict)
