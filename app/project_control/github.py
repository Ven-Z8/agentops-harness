"""Read-only GitHub Projects export through an injected GraphQL transport."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.io import atomic_write
from app.project_control.models import (
    BoardExport,
    BoardItem,
    ControlRoomState,
    ProvisionAction,
    ProvisioningPlan,
    ReconciliationReport,
    RemoteField,
    RemoteGitHubState,
    RemoteIssue,
    RemoteProject,
    RemoteProjectItem,
    RemoteView,
)
from app.project_control.roadmap import render_issue_body


class GhTransport(Protocol):
    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]: ...


class MutationTransport(Protocol):
    def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]: ...


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _GraphQLError(_StrictResponse):
    message: str = Field(min_length=1)


class _Option(_StrictResponse):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class _FieldDefinition(_StrictResponse):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    typename: str = Field(alias="__typename", min_length=1)
    dataType: str | None = None
    options: list[_Option] = Field(default_factory=list)


class _FieldDefinitions(_StrictResponse):
    nodes: list[_FieldDefinition]


class _PageInfo(_StrictResponse):
    hasNextPage: bool
    endCursor: str | None = Field(default=None, min_length=1)


class _FieldRef(_StrictResponse):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    typename: str = Field(alias="__typename", min_length=1)


class _FieldValue(_StrictResponse):
    id: str = Field(min_length=1)
    field: _FieldRef | None = None
    name: str | None = Field(default=None, min_length=1)
    text: str | None = Field(default=None, min_length=1)
    number: int | float | None = None
    date: str | None = Field(default=None, min_length=1)
    iterationId: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)


class _FieldValues(_StrictResponse):
    nodes: list[_FieldValue]


class _Repository(_StrictResponse):
    nameWithOwner: str = Field(
        min_length=3,
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )


class _Issue(_StrictResponse):
    number: int = Field(gt=0)
    title: str = Field(min_length=1)
    url: str
    repository: _Repository
    body: str


class _Item(_StrictResponse):
    id: str = Field(min_length=1)
    content: _Issue | None
    fieldValues: _FieldValues


class _Items(_StrictResponse):
    nodes: list[_Item]
    pageInfo: _PageInfo


class _Project(_StrictResponse):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    fields: _FieldDefinitions
    items: _Items


class _User(_StrictResponse):
    projectV2: _Project | None


class _Data(_StrictResponse):
    user: _User | None


class _GraphQLResponse(_StrictResponse):
    data: _Data | None = None
    errors: list[_GraphQLError] | None = None


TASK_ID_LINE = re.compile(r"(?m)^Task ID: (AO-(?:14D|P[1-6]|D\d{2}(?:-\d{2})?))$")

_READ_ONLY_QUERY = """
query ProjectBoard($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      title
      url
      fields(first: 100) {
        nodes {
          __typename
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2SingleSelectField { id name options { id name } }
          ... on ProjectV2IterationField { id name }
        }
      }
      items(first: 100, after: $after) {
        nodes {
          id
          content {
            ... on Issue {
              number title url body
              repository { nameWithOwner }
            }
          }
          fieldValues(first: 100) {
            nodes {
              id
              ... on ProjectV2ItemFieldSingleSelectValue {
                field {
                  __typename
                  ... on ProjectV2Field { id name }
                  ... on ProjectV2SingleSelectField { id name }
                }
                name
              }
              ... on ProjectV2ItemFieldTextValue {
                field {
                  __typename
                  ... on ProjectV2Field { id name }
                  ... on ProjectV2SingleSelectField { id name }
                }
                text
              }
              ... on ProjectV2ItemFieldNumberValue {
                field {
                  __typename
                  ... on ProjectV2Field { id name }
                  ... on ProjectV2SingleSelectField { id name }
                }
                number
              }
              ... on ProjectV2ItemFieldDateValue {
                field {
                  __typename
                  ... on ProjectV2Field { id name }
                  ... on ProjectV2SingleSelectField { id name }
                }
                date
              }
              ... on ProjectV2ItemFieldIterationValue {
                field {
                  __typename
                  ... on ProjectV2Field { id name }
                  ... on ProjectV2SingleSelectField { id name }
                  ... on ProjectV2IterationField { id name }
                }
                iterationId
                title
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()

_DISCOVERY_QUERY = """
query DiscoverProjects($owner: String!, $after: String) {
  user(login: $owner) {
    projectsV2(first: 100, after: $after) {
      nodes {
        id number title url
        fields(first: 100) { nodes { id name options { id name } } }
        views(first: 100) { nodes { id name } }
        items(first: 100) {
          nodes {
            id content {
              ... on Issue { id number title url body repository { nameWithOwner } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""".strip()

_KNOWN_FIELDS = {
    "Status",
    "Priority",
    "Day",
    "Phase",
    "Workstream",
    "Type",
    "Risk",
    "Evidence",
    "Harness",
    "Dependency",
    "Blocker",
    "Handoff",
    "Target date",
}
_IGNORED_BUILT_INS = {
    "Title",
    "Assignees",
    "Labels",
    "Milestone",
    "Repository",
    "Reviewers",
    "Iteration",
}
_IGNORED_BUILT_IN_TYPES = {"Iteration": {"ProjectV2IterationField"}}
_CONTROL_FIELD_TYPES = {
    "Status": {"ProjectV2SingleSelectField"},
    "Priority": {"ProjectV2SingleSelectField"},
    "Day": {"ProjectV2Field"},
    "Phase": {"ProjectV2SingleSelectField"},
    "Evidence": {"ProjectV2SingleSelectField"},
    "Harness": {"ProjectV2Field"},
    "Dependency": {"ProjectV2Field"},
    "Blocker": {"ProjectV2Field"},
    "Handoff": {"ProjectV2Field"},
}
_CONTROL_FIELD_DATA_TYPES = {
    "Day": {"NUMBER"},
    "Harness": {"TEXT"},
    "Dependency": {"TEXT"},
    "Blocker": {"TEXT"},
    "Handoff": {"TEXT"},
}
_STATUS = {
    "Inbox": "planned",
    "Ready": "ready",
    "In progress": "in-progress",
    "In review": "in-progress",
    "Blocked": "blocked",
    "Done": "done",
}
_EVIDENCE = {
    "Missing": "missing",
    "Inconclusive": "inconclusive",
    "Partial": "partial",
    "Verified": "verified",
}
_WORKSTREAMS = {"Trust", "kernel", "training", "packs", "VLM/VLA", "release"}
_TYPES = {"Roadmap", "phase", "outcome", "task", "decision", "research"}
_RISKS = {"Critical", "high", "medium", "low"}

PROVISION_PROJECT_NAME = "AgentOps Research Control Plane — 14-Day v0.1"
DESIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "Status": ("Inbox", "Ready", "In progress", "In review", "Blocked", "Done"),
    "Priority": ("P0", "P1", "P2", "P3"),
    "Day": tuple(f"Day {index}" for index in range(1, 15)),
    "Phase": tuple(f"Phase {index}" for index in range(1, 7)),
    "Workstream": ("Trust", "kernel", "training", "packs", "VLM/VLA", "release"),
    "Type": ("Roadmap", "phase", "outcome", "task", "decision", "research"),
    "Risk": ("Critical", "high", "medium", "low"),
    "Evidence": ("Missing", "inconclusive", "partial", "verified"),
    "Harness": ("Unassigned",),
    "Dependency": (),
    "Handoff": (),
    "Target date": (),
}
DESIRED_VIEWS = ("Inbox", "Kanban", "Phase", "Harness", "Trust Blockers", "Roadmap")
DESIRED_FIELD_OPTIONS = DESIRED_FIELDS
DESIRED_VIEW_NAMES = DESIRED_VIEWS

_MANAGED_BEGIN = "<!-- agentops-managed:start -->"
_MANAGED_END = "<!-- agentops-managed:end -->"

# Operation names are the complete mutation surface.  ApplyGhTransport never accepts a
# caller-provided GraphQL document, which prevents an apply run becoming an arbitrary API
# execution mechanism.
_MUTATION_QUERIES = {
    "create_project": (
        "mutation CreateProject($input: CreateProjectV2Input!) { "
        "createProjectV2(input: $input) { projectV2 { id number title url } } }"
    ),
    "update_project": (
        "mutation UpdateProject($input: UpdateProjectV2Input!) { "
        "updateProjectV2(input: $input) { projectV2 { id } } }"
    ),
    "create_field": (
        "mutation CreateField($input: CreateProjectV2FieldInput!) { "
        "createProjectV2Field(input: $input) { projectV2Field { id name } } }"
    ),
    "update_field": (
        "mutation UpdateField($input: UpdateProjectV2FieldInput!) { "
        "updateProjectV2Field(input: $input) { projectV2Field { id name } } }"
    ),
    "create_issue": (
        "mutation CreateIssue($input: CreateIssueInput!) { "
        "createIssue(input: $input) { issue { id number url title body } } }"
    ),
    "update_issue": (
        "mutation UpdateIssue($input: UpdateIssueInput!) { "
        "updateIssue(input: $input) { issue { id number url title body } } }"
    ),
    "add_item": (
        "mutation AddItem($input: AddProjectV2ItemByIdInput!) { "
        "addProjectV2ItemById(input: $input) { item { id } } }"
    ),
    "set_field_value": (
        "mutation SetFieldValue($input: UpdateProjectV2ItemFieldValueInput!) { "
        "updateProjectV2ItemFieldValue(input: $input) { projectV2Item { id } } }"
    ),
    "create_view": (
        "mutation CreateView($input: CreateProjectV2ViewInput!) { "
        "createProjectV2View(input: $input) { projectV2View { id name } } }"
    ),
    "update_view": (
        "mutation UpdateView($input: UpdateProjectV2ViewInput!) { "
        "updateProjectV2View(input: $input) { projectV2View { id name } } }"
    ),
}
MANUAL_VIEW_INSTRUCTIONS = tuple(
    f"Create the '{name}' view manually in GitHub Projects using the approved {name} layout."
    for name in DESIRED_VIEWS
)


def extract_task_id(body: str) -> str:
    match = TASK_ID_LINE.search(body)
    if match is None:
        raise InvalidControlRoom("GitHub issue is missing a stable task ID")
    return match.group(1)


def _response(value: dict[str, object]) -> _GraphQLResponse:
    try:
        parsed = _GraphQLResponse.model_validate(value)
    except ValidationError as error:
        raise InvalidControlRoom(f"GitHub GraphQL response schema is invalid: {error}") from error
    if parsed.errors:
        messages = "; ".join(error.message for error in parsed.errors)
        raise InvalidControlRoom(f"GitHub GraphQL query failed: {messages}")
    if parsed.data is None or parsed.data.user is None or parsed.data.user.projectV2 is None:
        raise InvalidControlRoom("GitHub GraphQL response is missing the requested project")
    return parsed


def _field_value(
    value: _FieldValue,
    definitions: dict[str, tuple[str, str, set[str]]],
) -> tuple[str, object] | None:
    if value.field is None or not value.field.name.strip():
        raise InvalidControlRoom("GitHub project field value is missing its field name")
    name = value.field.name
    if name not in _KNOWN_FIELDS and name not in _IGNORED_BUILT_INS:
        raise InvalidControlRoom(f"GitHub project contains unknown field: {name}")
    definition = definitions.get(name)
    if definition is None:
        raise InvalidControlRoom(f"GitHub field value references unknown definition: {name}")
    if value.field.id != definition[0]:
        raise InvalidControlRoom(f"GitHub field value does not match definition: {name}")
    if value.field.typename != definition[1]:
        raise InvalidControlRoom(f"GitHub field value type does not match definition: {name}")

    if name == "Iteration":
        if definition[1] != "ProjectV2IterationField" or (
            value.iterationId is None
            or value.title is None
            or any(
                field_value is not None
                for field_value in (value.name, value.text, value.number, value.date)
            )
        ):
            raise InvalidControlRoom("GitHub Iteration field value has an unsupported shape")
        return None

    if name in _IGNORED_BUILT_INS:
        return None

    populated = [
        ("name", value.name),
        ("text", value.text),
        ("number", value.number),
        ("date", value.date),
        ("iterationId", value.iterationId),
        ("title", value.title),
    ]
    present = [(kind, field_value) for kind, field_value in populated if field_value is not None]
    if len(present) != 1:
        raise InvalidControlRoom(f"GitHub field {name!r} has an unsupported value shape")
    kind, field_value = present[0]
    if kind == "name" and field_value not in definition[2]:
        raise InvalidControlRoom(f"GitHub field {name!r} has an unknown option: {field_value}")
    if name in {"Status", "Priority", "Phase", "Evidence", "Workstream", "Type", "Risk"}:
        if kind != "name":
            raise InvalidControlRoom(f"GitHub field {name!r} has an unsupported content type")
    elif name in {"Harness", "Dependency", "Blocker", "Handoff"} and kind != "text":
        raise InvalidControlRoom(f"GitHub field {name!r} has an unsupported content type")
    elif name == "Day" and kind != "number":
        raise InvalidControlRoom("GitHub field 'Day' has an unsupported content type")
    elif name == "Target date" and kind != "date":
        raise InvalidControlRoom("GitHub field 'Target date' has an unsupported content type")
    return name, field_value


def _phase_id(value: str) -> str:
    if value.startswith("AO-P") and value in {f"AO-P{index}" for index in range(1, 7)}:
        return value
    match = re.fullmatch(r"Phase ([1-6])", value)
    if match:
        return f"AO-P{match.group(1)}"
    raise InvalidControlRoom(f"GitHub field 'Phase' has an unknown option: {value}")


def _validate_canonical_issue(issue: _Issue) -> None:
    expected = f"https://github.com/{issue.repository.nameWithOwner}/issues/{issue.number}"
    if issue.url != expected:
        raise InvalidControlRoom(
            f"GitHub issue URL is not canonical for {issue.repository.nameWithOwner}: {issue.url}"
        )


def _board_item(
    item: _Item,
    definitions: dict[str, tuple[str, str, set[str]]],
    seen_item_ids: set[str],
    seen_task_ids: set[str],
) -> BoardItem:
    if item.id in seen_item_ids:
        raise InvalidControlRoom(f"GitHub project contains duplicate item ID: {item.id}")
    seen_item_ids.add(item.id)
    if item.content is None:
        raise InvalidControlRoom("GitHub project item has unsupported or missing content")
    _validate_canonical_issue(item.content)
    task_id = extract_task_id(item.content.body)
    if task_id in seen_task_ids:
        raise InvalidControlRoom(f"GitHub project contains duplicate stable task ID: {task_id}")
    seen_task_ids.add(task_id)

    values: dict[str, object] = {}
    value_ids: set[str] = set()
    for field_value in item.fieldValues.nodes:
        if field_value.id in value_ids:
            raise InvalidControlRoom(f"GitHub issue has duplicate field value ID: {field_value.id}")
        value_ids.add(field_value.id)
        mapped = _field_value(field_value, definitions)
        if mapped is None:
            continue
        name, value = mapped
        if name in values:
            raise InvalidControlRoom(f"GitHub issue has duplicate value for field: {name}")
        values[name] = value

    status_value = values.get("Status", "Inbox")
    status = _STATUS.get(status_value) if isinstance(status_value, str) else None
    if status is None:
        raise InvalidControlRoom(f"GitHub field 'Status' has an unknown option: {status_value}")
    priority = values.get("Priority", "P2")
    if priority not in {"P0", "P1", "P2", "P3"}:
        raise InvalidControlRoom(f"GitHub field 'Priority' has an unknown option: {priority}")
    day = values.get("Day")
    if day is not None and (
        isinstance(day, bool)
        or not isinstance(day, (int, float))
        or not math.isfinite(day)
        or int(day) != day
        or not 1 <= day <= 14
    ):
        raise InvalidControlRoom("GitHub field 'Day' must be an integer")
    phase = values.get("Phase")
    if phase is not None:
        if not isinstance(phase, str):
            raise InvalidControlRoom("GitHub field 'Phase' has an unsupported value")
        phase = _phase_id(phase)
    evidence = values.get("Evidence", "Missing")
    if not isinstance(evidence, str) or evidence not in _EVIDENCE:
        raise InvalidControlRoom(f"GitHub field 'Evidence' has an unknown option: {evidence}")
    for field_name, allowed in (
        ("Workstream", _WORKSTREAMS),
        ("Type", _TYPES),
        ("Risk", _RISKS),
    ):
        value = values.get(field_name)
        if value is not None and value not in allowed:
            raise InvalidControlRoom(f"GitHub field {field_name!r} has an unknown option: {value}")

    try:
        return BoardItem(
            task_id=task_id,
            title=item.content.title,
            status=status,
            priority=priority,
            day=int(day) if day is not None else None,
            phase_id=phase,
            issue_number=item.content.number,
            issue_url=item.content.url,
            evidence=_EVIDENCE[evidence],
            harness=values.get("Harness"),
            dependency=values.get("Dependency"),
            blocker=values.get("Blocker"),
            handoff=values.get("Handoff"),
        )
    except ValidationError as error:
        raise InvalidControlRoom(f"GitHub board item is invalid: {error}") from error


class SubprocessGhTransport:
    """Call the GitHub CLI with a fixed read-only GraphQL command."""

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        if re.search(r"\bmutation\b", query, flags=re.IGNORECASE):
            raise InvalidControlRoom("read-only GitHub transport refuses GraphQL mutations")
        payload = json.dumps({"query": query, "variables": variables})
        try:
            result = subprocess.run(
                ["gh", "api", "graphql", "--input", "-"],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise DependencyUnavailable("required executable 'gh' was not found") from error
        except (OSError, subprocess.SubprocessError) as error:
            raise DependencyUnavailable("GitHub CLI could not be executed") from error
        if result.returncode != 0:
            raise DependencyUnavailable("GitHub CLI is unavailable or unauthenticated")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise InvalidControlRoom("GitHub CLI returned invalid JSON") from error
        if not isinstance(value, dict):
            raise InvalidControlRoom("GitHub CLI returned a non-object JSON response")
        return value


class ApplyGhTransport:
    """Allowlisted GitHub mutation transport, constructed only for explicit apply."""

    def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
        query = _MUTATION_QUERIES.get(operation)
        if query is None:
            raise InvalidControlRoom(f"unsupported GitHub mutation operation: {operation}")
        payload = json.dumps({"query": query, "variables": variables})
        try:
            result = subprocess.run(
                ["gh", "api", "graphql", "--input", "-"],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise DependencyUnavailable("required executable 'gh' was not found") from error
        except (OSError, subprocess.SubprocessError) as error:
            raise DependencyUnavailable("GitHub CLI could not be executed") from error
        if result.returncode != 0:
            raise DependencyUnavailable("GitHub CLI is unavailable or unauthenticated")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise InvalidControlRoom("GitHub CLI returned invalid JSON") from error
        if not isinstance(value, dict):
            raise InvalidControlRoom("GitHub CLI returned a non-object JSON response")
        if value.get("errors"):
            raise InvalidControlRoom("GitHub mutation was rejected")
        return value


def _extract_remote_id(value: object) -> str | None:
    if isinstance(value, dict):
        direct = value.get("id")
        if isinstance(direct, str) and direct:
            return direct
        for child in value.values():
            found = _extract_remote_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _extract_remote_id(child)
            if found:
                return found
    return None


def _managed_issue_body(canonical: str) -> str:
    return f"{_MANAGED_BEGIN}\n{canonical.rstrip()}\n{_MANAGED_END}\n"


def merge_managed_issue_body(existing: str, canonical: str) -> str:
    """Replace only the managed section, preserving every byte outside its markers."""
    begin = existing.find(_MANAGED_BEGIN)
    end = existing.find(_MANAGED_END)
    managed = _managed_issue_body(canonical)
    if begin >= 0 and end >= begin + len(_MANAGED_BEGIN):
        suffix_start = end + len(_MANAGED_END)
        suffix = existing[suffix_start:]
        prefix = existing[:begin]
        return prefix + managed.rstrip("\n") + suffix
    if not existing:
        return canonical
    separator = "" if existing.endswith("\n") else "\n"
    return existing + separator + "\n" + managed


def _safe_remote_error(error: Exception) -> str:
    text = str(error).replace("\x1b", "")
    text = re.sub(r"(?i)(token|secret|password|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    return text[:500] or error.__class__.__name__


class GitHubProvisioner:
    def __init__(
        self, transport: MutationTransport | GhTransport, root: Path | None = None
    ) -> None:
        self._transport = transport
        self._root = root

    def plan(self, state: ControlRoomState, remote: RemoteGitHubState) -> ProvisioningPlan:
        if remote.owner != state.project.github_project.owner:
            raise InvalidControlRoom("remote GitHub owner does not match project configuration")
        if remote.repository != state.project.project.repository:
            raise InvalidControlRoom(
                "remote GitHub repository does not match project configuration"
            )
        if remote.project is not None and remote.project.name != PROVISION_PROJECT_NAME:
            raise InvalidControlRoom("remote GitHub project identity does not match desired name")
        project = ProvisionAction(
            resource="project",
            stable_key=PROVISION_PROJECT_NAME,
            action="reuse" if remote.project is not None else "create",
            remote_id=remote.project.id if remote.project else None,
            payload={
                "name": PROVISION_PROJECT_NAME,
                "owner": remote.owner,
                "repository": remote.repository,
            },
        )
        remote_fields = {field.name: field for field in remote.fields}
        field_actions = []
        for name, options in DESIRED_FIELDS.items():
            current = remote_fields.get(name)
            action = "create" if current is None else "reuse"
            if current is not None and tuple(current.options) != options:
                action = "update"
            field_actions.append(
                ProvisionAction(
                    resource="field",
                    stable_key=name,
                    action=action,
                    remote_id=current.id if current else None,
                    payload={"name": name, "options": list(options)},
                )
            )

        remote_issues = {issue.task_id: issue for issue in remote.issues}
        issue_actions = []
        for item in sorted(state.roadmap.items, key=lambda value: value.id):
            canonical = render_issue_body(item, state.roadmap)
            existing = remote_issues.get(item.id)
            if existing is None:
                action = "create"
                body = canonical
            else:
                body = merge_managed_issue_body(existing.body, canonical)
                action = (
                    "reuse"
                    if existing.title in {None, item.title} and existing.body in {"", canonical}
                    else "update"
                )
            issue_actions.append(
                ProvisionAction(
                    resource="issue",
                    stable_key=item.id,
                    action=action,
                    remote_id=existing.node_id if existing else None,
                    payload={
                        "task_id": item.id,
                        "title": item.title,
                        "body": body,
                        "repository": remote.repository,
                    },
                )
            )

        remote_items = {item.task_id: item for item in remote.items}
        item_actions = []
        for item in sorted(state.roadmap.items, key=lambda value: value.id):
            existing = remote_items.get(item.id)
            item_actions.append(
                ProvisionAction(
                    resource="item",
                    stable_key=item.id,
                    action="reuse" if existing else "create",
                    remote_id=existing.id if existing else None,
                    payload={"task_id": item.id, "project": PROVISION_PROJECT_NAME},
                )
            )

        field_value_actions = []
        for item in sorted(state.roadmap.items, key=lambda value: value.id):
            values = {
                "Status": _status_label(item.status),
                "Priority": item.priority,
                "Day": f"Day {item.day}" if item.day is not None else None,
                "Phase": _phase_label(item.phase_id),
                "Type": item.kind,
                "Risk": item.risk.capitalize() if item.risk == "critical" else item.risk,
                "Evidence": "Missing",
                "Harness": "Unassigned",
            }
            for field_name, value in values.items():
                if value is None:
                    continue
                stable_key = f"{item.id}:{field_name}"
                existing_item = remote_items.get(item.id)
                existing_value = (
                    existing_item.field_values.get(field_name)
                    if existing_item is not None
                    else None
                )
                existing_value_id: str | None = None
                if isinstance(existing_value, dict):
                    candidate = existing_value.get("id")
                    existing_value_id = candidate if isinstance(candidate, str) else None
                    existing_value = existing_value.get("value")
                value_action = "reuse" if existing_value == value else "create"
                field_value_actions.append(
                    ProvisionAction(
                        resource="field-value",
                        stable_key=stable_key,
                        action=value_action,
                        remote_id=existing_value_id,
                        payload={"task_id": item.id, "field": field_name, "value": value},
                    )
                )

        remote_views = {view.name: view for view in remote.views}
        view_actions = [
            ProvisionAction(
                resource="view",
                stable_key=name,
                action="reuse" if name in remote_views else "create",
                remote_id=remote_views[name].id if name in remote_views else None,
                payload={"name": name, "project": PROVISION_PROJECT_NAME},
            )
            for name in DESIRED_VIEWS
        ]
        return ProvisioningPlan(
            project=project,
            field_actions=sorted(field_actions, key=lambda action: action.stable_key),
            issue_actions=issue_actions,
            item_actions=item_actions,
            field_value_actions=field_value_actions,
            view_actions=view_actions,
        )

    def apply(self, plan: ProvisioningPlan) -> ReconciliationReport:
        completed: dict[str, str] = {}
        completed_actions: list[ProvisionAction] = []
        remaining = list(plan.actions)
        manual: list[str] = []
        error: str | None = None
        for action in plan.actions:
            if action.action == "reuse":
                if action.remote_id:
                    completed[action.stable_key] = action.remote_id
                completed_actions.append(action)
                remaining.pop(0)
                continue
            operation = _operation_for_action(action)
            variables = dict(action.payload)
            variables["stable_key"] = action.stable_key
            variables["remote_id"] = action.remote_id
            variables["project_id"] = completed.get(plan.project.stable_key, plan.project.remote_id)
            if action.resource in {"item", "field-value"}:
                task_id = str(action.payload.get("task_id", ""))
                variables["issue_id"] = completed.get(task_id)
            if action.resource == "field-value":
                field_name = str(action.payload.get("field", ""))
                variables["field_id"] = completed.get(field_name)
                variables["item_id"] = completed.get(str(action.payload.get("task_id", "")))
            try:
                if hasattr(self._transport, "mutate"):
                    response = self._transport.mutate(operation, variables)  # type: ignore[attr-defined]
                else:
                    response = self._transport.graphql(_MUTATION_QUERIES[operation], variables)  # type: ignore[attr-defined]
                remote_id = _extract_remote_id(response)
                if remote_id is None:
                    raise InvalidControlRoom("GitHub mutation returned no object ID")
                completed[action.stable_key] = remote_id
                completed_actions.append(action)
                remaining.pop(0)
            except NotImplementedError:
                if action.resource == "view":
                    manual.extend(MANUAL_VIEW_INSTRUCTIONS)
                    remaining.pop(0)
                    remaining.append(action)
                    continue
                error = "GitHub mutation capability is unsupported"
                break
            except (DependencyUnavailable, InvalidControlRoom):
                raise
            except Exception as exc:  # noqa: BLE001 - boundary converts remote failures safely
                error = _safe_remote_error(exc)
                break
        state = "partial" if error or manual else "success"
        report = ReconciliationReport(
            state=state,
            completed_object_ids=completed,
            completed_actions=completed_actions,
            remaining_actions=remaining,
            skipped_actions=list(remaining[1:]) if error and remaining else [],
            manual_instructions=list(dict.fromkeys(manual)),
            error=error,
        )
        return self._write_report(report)

    def _write_report(self, report: ReconciliationReport) -> ReconciliationReport:
        if self._root is None:
            return report
        relative = "coordination/artifacts/reports/github-provisioning.json"
        path = self._root / relative
        report_with_path = ReconciliationReport(**{**report.__dict__, "report_path": relative})
        try:
            atomic_write(path, report_with_path.to_json(), root=self._root)
        except OSError as error:
            raise InvalidControlRoom("unable to write reconciliation report") from error
        return report_with_path


def _status_label(status: object) -> str:
    return {
        "planned": "Inbox",
        "ready": "Ready",
        "in-progress": "In progress",
        "blocked": "Blocked",
        "done": "Done",
    }.get(str(status), "Inbox")


def _phase_label(phase_id: str | None) -> str | None:
    if phase_id is None:
        return None
    match = re.fullmatch(r"AO-P([1-6])", phase_id)
    return f"Phase {match.group(1)}" if match else phase_id


def _operation_for_action(action: ProvisionAction) -> str:
    names = {
        ("project", "create"): "create_project",
        ("project", "update"): "update_project",
        ("field", "create"): "create_field",
        ("field", "update"): "update_field",
        ("issue", "create"): "create_issue",
        ("issue", "update"): "update_issue",
        ("item", "create"): "add_item",
        ("field-value", "create"): "set_field_value",
        ("view", "create"): "create_view",
        ("view", "update"): "update_view",
    }
    try:
        return names[(action.resource, action.action)]
    except KeyError as error:
        raise InvalidControlRoom(
            f"unsupported provisioning action: {action.resource}/{action.action}"
        ) from error


def _discovery_page(response: dict[str, object]) -> tuple[list[object], tuple[bool, object]]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise InvalidControlRoom("GitHub discovery response is missing data")
    user = data.get("user")
    if not isinstance(user, dict):
        raise InvalidControlRoom("GitHub discovery response is missing user")
    projects = user.get("projectsV2")
    if not isinstance(projects, dict):
        raise InvalidControlRoom("GitHub discovery response is missing projects")
    nodes = projects.get("nodes")
    page_info = projects.get("pageInfo")
    if not isinstance(nodes, list) or not isinstance(page_info, dict):
        raise InvalidControlRoom("GitHub discovery projects page is malformed")
    has_next = page_info.get("hasNextPage")
    cursor = page_info.get("endCursor")
    if not isinstance(has_next, bool):
        raise InvalidControlRoom("GitHub discovery pageInfo is malformed")
    return nodes, (has_next, cursor)


def _parse_discovered_project(
    raw: dict[str, object], *, owner: str, repository: str
) -> RemoteGitHubState:
    project_id = raw.get("id")
    number = raw.get("number")
    name = raw.get("title", raw.get("name"))
    url = raw.get("url")
    if not all(isinstance(value, str) and value for value in (project_id, name, url)):
        raise InvalidControlRoom("GitHub discovery project identity is malformed")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise InvalidControlRoom("GitHub discovery project number is malformed")
    fields_raw = raw.get("fields", {"nodes": []})
    items_raw = raw.get(
        "items", {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}
    )
    if not isinstance(fields_raw, dict) or not isinstance(items_raw, dict):
        raise InvalidControlRoom("GitHub discovery fields or items are malformed")
    field_nodes = fields_raw.get("nodes")
    item_nodes = items_raw.get("nodes")
    if not isinstance(field_nodes, list) or not isinstance(item_nodes, list):
        raise InvalidControlRoom("GitHub discovery fields or items nodes are malformed")
    fields: list[RemoteField] = []
    for field in field_nodes:
        if (
            not isinstance(field, dict)
            or not isinstance(field.get("id"), str)
            or not isinstance(field.get("name"), str)
        ):
            raise InvalidControlRoom("GitHub discovery contains a malformed field")
        if field["name"] not in _KNOWN_FIELDS | _IGNORED_BUILT_INS:
            raise InvalidControlRoom(f"GitHub discovery contains unknown field: {field['name']}")
        options = field.get("options", [])
        if not isinstance(options, list):
            raise InvalidControlRoom("GitHub discovery field options are malformed")
        option_names: list[str] = []
        option_ids: set[str] = set()
        for option in options:
            if (
                not isinstance(option, dict)
                or not isinstance(option.get("id"), str)
                or not isinstance(option.get("name"), str)
            ):
                raise InvalidControlRoom("GitHub discovery contains a malformed field option")
            if option["id"] in option_ids or option["name"] in option_names:
                raise InvalidControlRoom("GitHub discovery contains duplicate field options")
            option_ids.add(option["id"])
            option_names.append(option["name"])
        fields.append(RemoteField(id=field["id"], name=field["name"], options=option_names))
    issues: list[RemoteIssue] = []
    items: list[RemoteProjectItem] = []
    seen_tasks: set[str] = set()
    for item in item_nodes:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise InvalidControlRoom("GitHub discovery contains a malformed project item")
        content = item.get("content")
        if not isinstance(content, dict):
            raise InvalidControlRoom("GitHub discovery project item is missing issue content")
        issue_id = content.get("id")
        issue_number = content.get("number")
        issue_title = content.get("title")
        issue_url = content.get("url")
        body = content.get("body")
        issue_repo = content.get("repository")
        if not isinstance(issue_repo, dict) or issue_repo.get("nameWithOwner") != repository:
            raise InvalidControlRoom(
                "GitHub discovery issue repository does not match configuration"
            )
        if (
            not isinstance(issue_id, str)
            or not isinstance(issue_number, int)
            or issue_number < 1
            or not isinstance(issue_title, str)
            or not isinstance(issue_url, str)
            or not isinstance(body, str)
        ):
            raise InvalidControlRoom("GitHub discovery issue is malformed")
        task_id = extract_task_id(body)
        if task_id in seen_tasks:
            raise InvalidControlRoom(
                f"GitHub discovery contains duplicate stable task ID: {task_id}"
            )
        seen_tasks.add(task_id)
        issues.append(
            RemoteIssue(
                task_id=task_id,
                node_id=issue_id,
                number=issue_number,
                url=issue_url,
                title=issue_title,
                body=body,
            )
        )
        items.append(RemoteProjectItem(id=item["id"], task_id=task_id))
    views_raw = raw.get("views", {"nodes": []})
    views_nodes = views_raw.get("nodes") if isinstance(views_raw, dict) else None
    if not isinstance(views_nodes, list):
        raise InvalidControlRoom("GitHub discovery views are malformed")
    views: list[RemoteView] = []
    for view in views_nodes:
        if (
            not isinstance(view, dict)
            or not isinstance(view.get("id"), str)
            or not isinstance(view.get("name"), str)
        ):
            raise InvalidControlRoom("GitHub discovery contains a malformed view")
        views.append(RemoteView(id=view["id"], name=view["name"]))
    return RemoteGitHubState(
        owner=owner,
        repository=repository,
        project=RemoteProject(id=project_id, number=number, name=name, url=url),
        issues=issues,
        fields=fields,
        items=items,
        views=views,
    )


class GitHubClient:
    def __init__(self, transport: GhTransport) -> None:
        self._transport = transport

    def discover_state(self, owner: str, repository: str, project_name: str) -> RemoteGitHubState:
        """Discover a named project with read-only, strict, paginated requests."""
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidControlRoom("GitHub project owner must not be empty")
        if not isinstance(project_name, str) or not project_name.strip():
            raise InvalidControlRoom("GitHub project name must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise InvalidControlRoom("GitHub repository must be canonical owner/name")
        after: str | None = None
        cursors: set[str] = set()
        matches: list[dict[str, object]] = []
        while True:
            try:
                response = self._transport.graphql(
                    _DISCOVERY_QUERY,
                    {
                        "owner": owner,
                        "repository": repository,
                        "project_name": project_name,
                        "after": after,
                    },
                )
            except StopIteration as error:
                raise InvalidControlRoom("GitHub discovery ended during pagination") from error
            if not isinstance(response, dict):
                raise InvalidControlRoom("GitHub discovery returned a non-object response")
            if response.get("errors"):
                raise DependencyUnavailable("GitHub discovery failed")
            projects, page_info = _discovery_page(response)
            for raw in projects:
                if not isinstance(raw, dict):
                    raise InvalidControlRoom("GitHub discovery contains a malformed project")
                name = raw.get("title", raw.get("name"))
                if name == project_name:
                    matches.append(raw)
            if not page_info[0]:
                break
            cursor = page_info[1]
            if not isinstance(cursor, str) or not cursor:
                raise InvalidControlRoom("GitHub discovery hasNextPage without a cursor")
            if cursor in cursors:
                raise InvalidControlRoom("GitHub discovery cursor cycle detected")
            cursors.add(cursor)
            after = cursor
        if len(matches) > 1:
            raise InvalidControlRoom(f"GitHub project name is ambiguous: {project_name}")
        if not matches:
            return RemoteGitHubState(owner=owner, repository=repository)
        return _parse_discovered_project(matches[0], owner=owner, repository=repository)

    def export_project(
        self,
        owner: str,
        number: int,
        expected_repository: str | None = None,
    ) -> BoardExport:
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidControlRoom("GitHub project owner must not be empty")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise InvalidControlRoom("GitHub project number must be positive")
        if expected_repository is not None and (
            not isinstance(expected_repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_repository)
        ):
            raise InvalidControlRoom("expected GitHub repository must be canonical owner/name")

        after: str | None = None
        cursors: set[str] = set()
        seen_item_ids: set[str] = set()
        seen_task_ids: set[str] = set()
        project: _Project | None = None
        project_repository: str | None = expected_repository
        exported: list[BoardItem] = []
        while True:
            try:
                response = _response(
                    self._transport.graphql(
                        _READ_ONLY_QUERY,
                        {"owner": owner, "number": number, "after": after},
                    )
                )
            except StopIteration as error:
                raise InvalidControlRoom("GitHub transport ended during pagination") from error
            current = response.data.user.projectV2
            if project is None:
                project = current
            elif current.id != project.id or current.url != project.url:
                raise InvalidControlRoom("GitHub project identity changed during pagination")
            for raw_item in current.items.nodes:
                if raw_item.content is None:
                    raise InvalidControlRoom(
                        "GitHub project item has unsupported or missing content"
                    )
                page_repository = raw_item.content.repository.nameWithOwner
                if project_repository is None:
                    project_repository = page_repository
                elif page_repository != project_repository:
                    raise InvalidControlRoom("GitHub issue repository changed during pagination")
            definitions: dict[str, tuple[str, str, set[str]]] = {}
            definition_ids: set[str] = set()
            for definition in current.fields.nodes:
                if definition.name in definitions:
                    raise InvalidControlRoom(
                        f"GitHub project has duplicate field: {definition.name}"
                    )
                if definition.id in definition_ids:
                    raise InvalidControlRoom(
                        f"GitHub project has duplicate definition ID: {definition.id}"
                    )
                definition_ids.add(definition.id)
                if definition.name not in _KNOWN_FIELDS | _IGNORED_BUILT_INS:
                    raise InvalidControlRoom(
                        f"GitHub project contains unknown field/custom field: {definition.name}"
                    )
                option_ids = [option.id for option in definition.options]
                option_names = [option.name for option in definition.options]
                if len(option_ids) != len(set(option_ids)):
                    raise InvalidControlRoom(
                        f"GitHub field {definition.name!r} has duplicate option IDs"
                    )
                if len(option_names) != len(set(option_names)):
                    raise InvalidControlRoom(
                        f"GitHub field {definition.name!r} has duplicate option names"
                    )
                expected_types = _CONTROL_FIELD_TYPES.get(definition.name)
                if expected_types and definition.typename not in expected_types:
                    raise InvalidControlRoom(
                        f"GitHub field {definition.name!r} has wrong definition type"
                    )
                ignored_types = _IGNORED_BUILT_IN_TYPES.get(definition.name)
                if ignored_types and definition.typename not in ignored_types:
                    raise InvalidControlRoom(
                        f"GitHub built-in field {definition.name!r} has wrong definition type"
                    )
                expected_data_types = _CONTROL_FIELD_DATA_TYPES.get(definition.name)
                if (
                    expected_data_types
                    and definition.dataType is not None
                    and definition.dataType not in expected_data_types
                ):
                    raise InvalidControlRoom(
                        f"GitHub field {definition.name!r} has wrong definition data type"
                    )
                if definition.typename == "ProjectV2Field" and definition.dataType is None:
                    raise InvalidControlRoom(
                        f"GitHub field {definition.name!r} is missing dataType metadata"
                    )
                definitions[definition.name] = (
                    definition.id,
                    definition.typename,
                    set(option_names),
                )
            defined_controls = definitions.keys() & _CONTROL_FIELD_TYPES.keys()
            if defined_controls and defined_controls != _CONTROL_FIELD_TYPES.keys():
                missing = sorted(_CONTROL_FIELD_TYPES.keys() - defined_controls)
                raise InvalidControlRoom(
                    f"GitHub project is missing required control fields: {', '.join(missing)}"
                )
            exported.extend(
                _board_item(item, definitions, seen_item_ids, seen_task_ids)
                for item in current.items.nodes
            )
            page_info = current.items.pageInfo
            if not page_info.hasNextPage:
                break
            if not page_info.endCursor:
                raise InvalidControlRoom("GitHub pagination hasNextPage without a cursor")
            if page_info.endCursor in cursors:
                raise InvalidControlRoom("GitHub pagination cursor cycle detected")
            cursors.add(page_info.endCursor)
            after = page_info.endCursor

        assert project is not None
        try:
            return BoardExport(
                project_url=project.url,
                repository=project_repository,
                items=exported,
            )
        except ValidationError as error:
            raise InvalidControlRoom(f"GitHub board export is invalid: {error}") from error
