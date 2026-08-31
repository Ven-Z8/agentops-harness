"""Read-only GitHub Projects export through an injected GraphQL transport."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.project_control.artifacts import load_artifact_index
from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.io import atomic_write
from app.project_control.models import (
    ArtifactIndex,
    ArtifactRecord,
    BoardExport,
    BoardItem,
    ControlRoomState,
    EvidenceState,
    ProvisionAction,
    ProvisioningPlan,
    ReconciliationAction,
    ReconciliationId,
    ReconciliationReport,
    RemoteField,
    RemoteFieldValue,
    RemoteGitHubState,
    RemoteIssue,
    RemoteOption,
    RemoteProject,
    RemoteProjectItem,
    RemoteView,
)
from app.project_control.roadmap import load_roadmap, render_issue_body


class GhTransport(Protocol):
    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]: ...


class MutationTransport(Protocol):
    def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]: ...


class MutationInputError(InvalidControlRoom):
    """Local dependency/input validation failed before a remote mutation was attempted."""


class UnsupportedViewOperation(InvalidControlRoom):
    """The installed GitHub schema/permissions do not expose view mutation support."""


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
query DiscoverProjects(
  $owner: String!, $repository_name: String!, $after: String, $issues_after: String
) {
  user(login: $owner) {
    id
    projectsV2(first: 100, after: $after) {
      nodes {
        id number title url
        fields(first: 100) {
          nodes { id name dataType options { id name } }
          pageInfo { hasNextPage endCursor }
        }
        views(first: 100) { nodes { id name } pageInfo { hasNextPage endCursor } }
        items(first: 100) {
          nodes {
            id content {
              ... on Issue { id number title url body repository { nameWithOwner } }
            }
            fieldValues(first: 100) {
              nodes { id field { id name } name text number date }
              pageInfo { hasNextPage endCursor }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
  repository(owner: $owner, name: $repository_name) {
      id
      issues(first: 100, after: $issues_after) {
        nodes { id number title url body repository { nameWithOwner } }
        pageInfo { hasNextPage endCursor }
      }
  }
}
""".strip()

# Nested connections are fetched with separate fixed read-only documents.  Keeping these
# documents explicit prevents pagination from becoming an arbitrary GraphQL surface.
_NESTED_FIELDS_QUERY = """query ProjectFields($id: ID!, $after: String) {
  node(id: $id) { ... on ProjectV2 { fields(first: 100, after: $after) {
    nodes { id name dataType options { id name } } pageInfo { hasNextPage endCursor }
  } } }
}""".strip()
_NESTED_OPTIONS_QUERY = """query FieldOptions($id: ID!, $after: String) {
  node(id: $id) { ... on ProjectV2SingleSelectField { options(first: 100, after: $after) {
    nodes { id name } pageInfo { hasNextPage endCursor }
  } } }
}""".strip()
_NESTED_VIEWS_QUERY = """query ProjectViews($id: ID!, $after: String) {
  node(id: $id) { ... on ProjectV2 { views(first: 100, after: $after) {
    nodes { id name layout groupBy sortBy filter } pageInfo { hasNextPage endCursor }
  } } }
}""".strip()
_NESTED_ITEMS_QUERY = """query ProjectItems($id: ID!, $after: String) {
  node(id: $id) { ... on ProjectV2 { items(first: 100, after: $after) {
    nodes { id content { ... on Issue { id number title url body repository { nameWithOwner } } }
      fieldValues(first: 100) { nodes { id field { id name } name text number date optionId }
        pageInfo { hasNextPage endCursor } } }
    pageInfo { hasNextPage endCursor }
  } } }
}""".strip()
_NESTED_ITEM_VALUES_QUERY = """query ItemFieldValues($id: ID!, $after: String) {
  node(id: $id) { ... on ProjectV2Item { fieldValues(first: 100, after: $after) {
    nodes { id field { id name } name text number date optionId }
    pageInfo { hasNextPage endCursor }
  } } }
}""".strip()

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
    # Legacy boards may expose Day as a number; provisioning always creates the
    # approved single-select field and resolves its option ID.
    "Day": {"ProjectV2SingleSelectField", "ProjectV2Field"},
    "Phase": {"ProjectV2SingleSelectField"},
    "Evidence": {"ProjectV2SingleSelectField"},
    "Harness": {"ProjectV2Field"},
    "Dependency": {"ProjectV2Field"},
    "Blocker": {"ProjectV2Field"},
    "Handoff": {"ProjectV2Field"},
}
_CONTROL_FIELD_DATA_TYPES = {
    "Day": {"NUMBER", "SINGLE_SELECT"},
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
FIELD_TYPES: dict[str, str] = {
    "Status": "single-select",
    "Priority": "single-select",
    "Day": "single-select",
    "Phase": "single-select",
    "Workstream": "single-select",
    "Type": "single-select",
    "Risk": "single-select",
    "Evidence": "single-select",
    "Harness": "text",
    "Dependency": "text",
    "Handoff": "text",
    "Target date": "date",
}
DESIRED_VIEWS = ("Inbox", "Kanban", "Phase", "Harness", "Trust Blockers", "Roadmap")
VIEW_SPECS = {
    "Inbox": {
        "layout": "TABLE",
        "group_by": "Status",
        "sort_by": "created_at",
        "filter": "Status:Inbox",
    },
    "Kanban": {
        "layout": "BOARD",
        "group_by": "Status",
        "sort_by": "Priority",
        "filter": "",
    },
    "Phase": {"layout": "TABLE", "group_by": "Phase", "sort_by": "Day", "filter": ""},
    "Harness": {
        "layout": "TABLE",
        "group_by": "Harness",
        "sort_by": "Priority",
        "filter": "",
    },
    "Trust Blockers": {
        "layout": "TABLE",
        "group_by": "Status",
        "sort_by": "Priority",
        "filter": "Phase:Phase 1 Priority:P0,P1 Status:Done!=true",
    },
    "Roadmap": {
        "layout": "TABLE",
        "group_by": "Day",
        "sort_by": "Target date",
        "filter": "",
    },
}
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
        "createProjectV2Field(input: $input) { projectV2Field { id name dataType "
        "options { id name } } }"
    ),
    "update_field": (
        "mutation UpdateField($input: UpdateProjectV2FieldInput!) { "
        "updateProjectV2Field(input: $input) { projectV2Field { id name dataType "
        "options { id name } } }"
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
    elif name == "Target date" and kind != "date":
        raise InvalidControlRoom("GitHub field 'Target date' has an unsupported content type")
    if name == "Day":
        if definition[1] == "ProjectV2Field" and kind == "number":
            return name, field_value
        if definition[1] == "ProjectV2SingleSelectField" and kind == "name":
            match = re.fullmatch(r"Day ([1-9]|1[0-4])", str(field_value))
            if match is None:
                raise InvalidControlRoom("GitHub field 'Day' has an unknown option")
            return name, int(match.group(1))
        raise InvalidControlRoom("GitHub field 'Day' has an unsupported content type")
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
        payload = json.dumps(
            {"query": query, "variables": {"input": _typed_input(operation, variables)}}
        )
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
            if operation in {"create_view", "update_view"}:
                messages = " ".join(
                    str(error.get("message", ""))
                    for error in value["errors"]
                    if isinstance(error, dict)
                ).lower()
                if any(
                    token in messages
                    for token in (
                        "unknown field",
                        "unknown argument",
                        "not permitted",
                        "permission",
                        "unsupported",
                    )
                ):
                    raise UnsupportedViewOperation("GitHub view mutation is unsupported")
            raise InvalidControlRoom("GitHub mutation was rejected")
        if _mutation_id(operation, value) is None:
            raise InvalidControlRoom("GitHub mutation response schema is invalid")
        return value


def _required_id(variables: dict[str, object], key: str) -> str:
    value = variables.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or not re.fullmatch(r"^[A-Za-z0-9_:-]+$", value)
    ):
        raise MutationInputError(f"GitHub mutation is missing a valid dependency ID: {key}")
    return value


def _required_text(variables: dict[str, object], key: str) -> str:
    value = variables.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MutationInputError(f"GitHub mutation is missing required text: {key}")
    return value


def _typed_input(operation: str, variables: dict[str, object]) -> dict[str, object]:
    """Build the exact, operation-specific GraphQL input; no caller text is accepted."""
    if operation == "create_project":
        return {
            "ownerId": _required_id(variables, "owner_id"),
            "title": _required_text(variables, "title"),
        }
    if operation == "update_project":
        return {
            "projectId": _required_id(variables, "project_id"),
            "title": _required_text(variables, "title"),
        }
    if operation in {"create_field", "update_field"}:
        field_id = (
            {"fieldId": _required_id(variables, "field_id")} if operation == "update_field" else {}
        )
        result = {
            "projectId": _required_id(variables, "project_id"),
            "name": _required_text(variables, "name"),
            "dataType": _required_text(variables, "data_type"),
            **field_id,
        }
        options = variables.get("options", [])
        if not isinstance(options, list) or not all(
            isinstance(option, str) and option for option in options
        ):
            raise MutationInputError("GitHub mutation field options are malformed")
        if options:
            result["singleSelectOptions"] = options
        return result
    if operation in {"create_issue", "update_issue"}:
        result = {
            "repositoryId": _required_id(variables, "repository_id")
            if operation == "create_issue"
            else None,
            "issueId": _required_id(variables, "issue_id") if operation == "update_issue" else None,
            "title": _required_text(variables, "title"),
            "body": _required_text(variables, "body"),
        }
        return {key: value for key, value in result.items() if value is not None}
    if operation == "add_item":
        return {
            "projectId": _required_id(variables, "project_id"),
            "contentId": _required_id(variables, "content_id"),
        }
    if operation == "set_field_value":
        result = {
            "projectId": _required_id(variables, "project_id"),
            "itemId": _required_id(variables, "item_id"),
            "fieldId": _required_id(variables, "field_id"),
        }
        field_type = variables.get("field_type")
        logical = variables.get("logical_value")
        if field_type not in {"single-select", "text", "number", "date"}:
            raise MutationInputError("GitHub mutation field value has an invalid field type")
        if field_type == "single-select":
            option_id = variables.get("option_id")
            if not isinstance(option_id, str) or not re.fullmatch(r"^[A-Za-z0-9_:-]+$", option_id):
                raise MutationInputError("GitHub mutation field value is missing a valid option ID")
            if not isinstance(logical, str) or not logical.strip():
                raise MutationInputError("GitHub mutation single-select value is malformed")
            result["singleSelectOptionId"] = option_id
        elif field_type == "text":
            if not isinstance(logical, str):
                raise MutationInputError("GitHub mutation text value is malformed")
            result["text"] = logical
        elif field_type == "number":
            if (
                isinstance(logical, bool)
                or not isinstance(logical, (int, float))
                or not math.isfinite(logical)
            ):
                raise MutationInputError("GitHub mutation number value is malformed")
            result["number"] = logical
        else:
            if not isinstance(logical, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", logical):
                raise MutationInputError("GitHub mutation date value is malformed")
            result["date"] = logical
        return result
    if operation in {"create_view", "update_view"}:
        result = {
            "projectId": _required_id(variables, "project_id"),
            "name": _required_text(variables, "name"),
            "layout": _required_text(variables, "layout"),
        }
        for key in ("group_by", "sort_by", "filter"):
            if key in variables:
                result[key] = variables[key]
        if operation == "update_view":
            result["viewId"] = _required_id(variables, "view_id")
        return result
    raise InvalidControlRoom(f"unsupported GitHub mutation operation: {operation}")


_MUTATION_RESPONSE_PATHS = {
    "create_project": ("createProjectV2", "projectV2", "id"),
    "update_project": ("updateProjectV2", "projectV2", "id"),
    "create_field": ("createProjectV2Field", "projectV2Field", "id"),
    "update_field": ("updateProjectV2Field", "projectV2Field", "id"),
    "create_issue": ("createIssue", "issue", "id"),
    "update_issue": ("updateIssue", "issue", "id"),
    "add_item": ("addProjectV2ItemById", "item", "id"),
    "set_field_value": ("updateProjectV2ItemFieldValue", "projectV2Item", "id"),
    "create_view": ("createProjectV2View", "projectV2View", "id"),
    "update_view": ("updateProjectV2View", "projectV2View", "id"),
}


def _mutation_id(operation: str, response: object) -> str | None:
    if not isinstance(response, dict):
        raise InvalidControlRoom("GitHub mutation response is not an object")
    if response.get("errors"):
        raise InvalidControlRoom("GitHub mutation response contains errors")
    if set(response) != {"data"}:
        raise InvalidControlRoom("GitHub mutation response envelope is invalid")
    current: object = response.get("data")
    for key in _MUTATION_RESPONSE_PATHS[operation]:
        if not isinstance(current, dict) or key not in current:
            raise InvalidControlRoom("GitHub mutation response path is malformed")
        current = current[key]
    if isinstance(current, str) and re.fullmatch(r"^[A-Za-z0-9_:-]+$", current):
        return current
    return None


def _mutation_option_ids(operation: str, response: object) -> dict[str, str]:
    """Return option identities from the one allowed field mutation envelope."""
    if operation not in {"create_field", "update_field"}:
        return {}
    if not isinstance(response, dict) or set(response) != {"data"}:
        raise InvalidControlRoom("GitHub field mutation response envelope is invalid")
    current: object = response.get("data")
    for key in _MUTATION_RESPONSE_PATHS[operation][:-1]:
        if not isinstance(current, dict) or key not in current:
            raise InvalidControlRoom("GitHub field mutation response path is malformed")
        current = current[key]
    if not isinstance(current, dict) or not isinstance(current.get("options"), list):
        raise InvalidControlRoom("GitHub field mutation response options are malformed")
    result: dict[str, str] = {}
    for option in current["options"]:
        if (
            not isinstance(option, dict)
            or set(option) != {"id", "name"}
            or not isinstance(option["id"], str)
            or not re.fullmatch(r"^[A-Za-z0-9_:-]+$", option["id"])
            or not isinstance(option["name"], str)
            or option["name"] in result
        ):
            raise InvalidControlRoom("GitHub field mutation returned malformed options")
        result[option["name"]] = option["id"]
    return result


def _managed_issue_body(canonical: str) -> str:
    return f"{_MANAGED_BEGIN}\n{canonical.rstrip()}\n{_MANAGED_END}\n"


def merge_managed_issue_body(existing: str, canonical: str) -> str:
    """Replace only the managed section, preserving every byte outside its markers."""
    begin_count = existing.count(_MANAGED_BEGIN)
    end_count = existing.count(_MANAGED_END)
    if (begin_count or end_count) and (begin_count != 1 or end_count != 1):
        raise InvalidControlRoom("issue body has duplicate or unbalanced managed markers")
    begin = existing.find(_MANAGED_BEGIN)
    end = existing.find(_MANAGED_END)
    managed = _managed_issue_body(canonical)
    if begin >= 0 and end >= begin + len(_MANAGED_BEGIN):
        suffix_start = end + len(_MANAGED_END)
        suffix = existing[suffix_start:]
        prefix = existing[:begin]
        return prefix + managed.rstrip("\n") + suffix
    if not existing:
        return managed
    separator = "" if existing.endswith("\n") else "\n"
    return existing + separator + "\n" + managed


def _managed_issue_content(body: str) -> str | None:
    begin_count = body.count(_MANAGED_BEGIN)
    end_count = body.count(_MANAGED_END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise InvalidControlRoom("issue body has duplicate or unbalanced managed markers")
    begin = body.find(_MANAGED_BEGIN)
    end = body.find(_MANAGED_END)
    if end < begin + len(_MANAGED_BEGIN):
        raise InvalidControlRoom("issue body has unbalanced managed markers")
    return body[begin + len(_MANAGED_BEGIN) : end].strip("\r\n")


def _safe_remote_error(error: Exception) -> str:
    text = str(error).replace("\x1b", "")
    text = re.sub(r"(?i)(token|secret|password|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    return text[:500] or error.__class__.__name__


class GitHubProvisioner:
    def __init__(
        self,
        transport: MutationTransport | GhTransport,
        root: Path | None = None,
        rediscover: Callable[[], RemoteGitHubState] | None = None,
    ) -> None:
        self._transport = transport
        self._root = root.resolve(strict=True) if root is not None else None
        self._rediscover = rediscover

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
                "owner_id": remote.owner_id,
                "repository": remote.repository,
                "repository_id": remote.repository_id,
            },
        )
        remote_fields = {field.name: field for field in remote.fields}
        field_actions = []
        for name, options in DESIRED_FIELDS.items():
            current = remote_fields.get(name)
            action = "create" if current is None else "reuse"
            if current is not None and tuple(option.name for option in current.options) != options:
                action = "update"
            field_actions.append(
                ProvisionAction(
                    resource="field",
                    stable_key=name,
                    action=action,
                    remote_id=current.id if current else None,
                    payload={
                        "name": name,
                        "options": list(options),
                        "data_type": _field_data_type(name),
                        "field_type": FIELD_TYPES[name],
                        "option_ids": {option.name: option.id for option in current.options}
                        if current is not None
                        else {},
                    },
                )
            )

        remote_issues = {issue.task_id: issue for issue in remote.issues}
        issue_actions = []
        for item in sorted(state.roadmap.items, key=lambda value: value.id):
            canonical = render_issue_body(item, state.roadmap)
            existing = remote_issues.get(item.id)
            if existing is None:
                action = "create"
                body = _managed_issue_body(canonical)
            else:
                body = merge_managed_issue_body(existing.body, canonical)
                managed_content = _managed_issue_content(existing.body)
                action = (
                    "reuse"
                    if existing.title in {None, item.title}
                    and (existing.body == "" or managed_content == canonical)
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
                        "repository_id": remote.repository_id,
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
                    payload={
                        "task_id": item.id,
                        "project": PROVISION_PROJECT_NAME,
                        "content_id": remote_issues[item.id].node_id
                        if item.id in remote_issues
                        else None,
                    },
                )
            )

        field_value_actions = []
        for item in sorted(state.roadmap.items, key=lambda value: value.id):
            values = {
                "Status": _status_label(item.status),
                "Priority": item.priority,
                "Day": f"Day {item.day}" if item.day is not None else None,
                "Phase": _phase_label(item.phase_id),
                "Workstream": "Trust",
                "Type": item.kind,
                "Risk": item.risk.capitalize() if item.risk == "critical" else item.risk,
                "Evidence": "Missing",
                "Harness": "Unassigned",
                "Dependency": ", ".join(item.dependencies) if item.dependencies else "",
                "Handoff": "",
                "Target date": None,
            }
            for field_name, value in values.items():
                if value is None:
                    continue
                stable_key = f"{item.id}:{field_name}"
                existing_item = remote_items.get(item.id)
                existing_value = next(
                    (
                        value
                        for value in (existing_item.field_values if existing_item else ())
                        if value.field_id
                        == next(
                            (field.id for field in remote.fields if field.name == field_name), ""
                        )
                    ),
                    None,
                )
                existing_value_id: str | None = None
                if isinstance(existing_value, RemoteFieldValue):
                    existing_value_id = existing_value.id
                    existing_value = existing_value.value
                value_action = "reuse" if existing_value == value else "create"
                field_type = FIELD_TYPES[field_name]
                field_definition = next(
                    (field for field in remote.fields if field.name == field_name), None
                )
                option_ids = (
                    {option.name: option.id for option in field_definition.options}
                    if field_definition
                    else {}
                )
                field_value_actions.append(
                    ProvisionAction(
                        resource="field-value",
                        stable_key=stable_key,
                        action=value_action,
                        remote_id=existing_value_id,
                        payload={
                            "task_id": item.id,
                            "field": field_name,
                            "field_type": field_type,
                            "logical_value": value,
                            "option_id": option_ids.get(value) if isinstance(value, str) else None,
                        },
                    )
                )

        remote_views = {view.name: view for view in remote.views}
        view_actions = [
            ProvisionAction(
                resource="view",
                stable_key=name,
                action="reuse" if name in remote_views else "create",
                remote_id=remote_views[name].id if name in remote_views else None,
                payload={"name": name, "project": PROVISION_PROJECT_NAME, **VIEW_SPECS[name]},
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
        completed_options: dict[str, dict[str, str]] = {}
        attempted_actions: list[ProvisionAction] = []
        completed_actions: list[ProvisionAction] = []
        remaining = list(plan.actions)
        manual: list[str] = []
        error: str | None = None
        mutation_confirmed = False
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
            if action.resource == "issue" and action.action == "update":
                variables["issue_id"] = action.remote_id
            if action.resource == "field" and action.action == "update":
                variables["field_id"] = action.remote_id
            if action.resource == "view" and action.action == "update":
                variables["view_id"] = action.remote_id
            if action.resource in {"item", "field-value"}:
                task_id = str(action.payload.get("task_id", ""))
                variables["issue_id"] = completed.get(task_id)
                variables["content_id"] = completed.get(task_id)
            if action.resource == "field-value":
                field_name = str(action.payload.get("field", ""))
                variables["field_id"] = completed.get(field_name)
                variables["item_id"] = completed.get(str(action.payload.get("task_id", "")))
                if action.payload.get("field_type") == "single-select" and not variables.get(
                    "option_id"
                ):
                    logical = action.payload.get("logical_value")
                    variables["option_id"] = completed_options.get(field_name, {}).get(str(logical))
            try:
                attempted_actions.append(action)
                if hasattr(self._transport, "mutate"):
                    response = self._transport.mutate(operation, variables)  # type: ignore[attr-defined]
                else:
                    response = self._transport.graphql(_MUTATION_QUERIES[operation], variables)  # type: ignore[attr-defined]
                remote_id = _mutation_id(operation, response)
                if remote_id is None:
                    raise InvalidControlRoom("GitHub mutation returned no object ID")
                _validate_mutation_identity(operation, response, action)
                completed[action.stable_key] = remote_id
                if action.resource == "field":
                    completed_options[action.stable_key] = _mutation_option_ids(operation, response)
                completed_actions.append(action)
                mutation_confirmed = True
                remaining.pop(0)
            except (NotImplementedError, UnsupportedViewOperation):
                if action.resource == "view":
                    manual.extend(MANUAL_VIEW_INSTRUCTIONS)
                    remaining.pop(0)
                    remaining.append(action)
                    continue
                error = "GitHub mutation capability is unsupported"
                break
            except MutationInputError:
                raise
            except DependencyUnavailable as exc:
                if not mutation_confirmed:
                    raise
                error = _safe_remote_error(exc)
                break
            except InvalidControlRoom as exc:
                error = _safe_remote_error(exc)
                break
            except Exception as exc:  # noqa: BLE001 - boundary converts remote failures safely
                error = _safe_remote_error(exc)
                break
        state = "partial" if error or manual else "success"
        report = ReconciliationReport(
            state=state,
            completed_object_ids=tuple(
                ReconciliationId(stable_key=key, remote_id=value)
                for key, value in sorted(completed.items())
            ),
            attempted_actions=tuple(_action_record(action) for action in attempted_actions),
            completed_actions=tuple(_action_record(action) for action in completed_actions),
            remaining_actions=tuple(_action_record(action) for action in remaining),
            skipped_actions=tuple(
                _action_record(action)
                for action in (list(remaining[1:]) if error and remaining else [])
            ),
            manual_instructions=tuple(dict.fromkeys(manual)),
            error=error,
        )
        if report.state == "success":
            if self._rediscover is None:
                report = report.model_copy(
                    update={
                        "state": "partial",
                        "error": "post-apply read-only rediscovery is required",
                    }
                )
            else:
                try:
                    discovered = self._rediscover()
                    mismatch = _reconcile_plan(plan, discovered)
                except Exception as exc:  # noqa: BLE001 - reconciliation boundary
                    mismatch = _safe_remote_error(exc)
                if mismatch is not None:
                    report = report.model_copy(update={"state": "partial", "error": mismatch})
        return self._write_report(report)

    def _write_report(self, report: ReconciliationReport) -> ReconciliationReport:
        if self._root is None:
            return report
        relative = "coordination/artifacts/reports/github-provisioning.json"
        path = self._root / relative
        report_with_path = report.model_copy(update={"report_path": relative})
        report_content = report_with_path.to_json()
        old_report: bytes | None = None
        old_index: bytes | None = None
        index_path = self._root / "coordination/artifacts/index.yaml"
        try:
            old_report = path.read_bytes() if path.exists() else None
            old_index = index_path.read_bytes() if index_path.exists() else None
            atomic_write(path, report_content, root=self._root)
            index = load_artifact_index(self._root)
            task_id = "AO-14D"
            roadmap = load_roadmap(self._root)
            if not any(item.id == task_id for item in roadmap.items):
                task_id = roadmap.items[0].id
            artifact = ArtifactRecord(
                id=f"github-provisioning-{hashlib.sha256(report_content.encode()).hexdigest()[:12]}",
                task_id=task_id,
                kind="github-provisioning-report",
                availability="repository",
                locator=relative,
                sha256=hashlib.sha256(report_content.encode()).hexdigest(),
                evidence_state=(
                    EvidenceState.VERIFIED if report.state == "success" else EvidenceState.PARTIAL
                ),
                created_at=report.updated_at,
                producer="github-provisioner",
            )
            artifacts = [existing for existing in index.artifacts if existing.kind != artifact.kind]
            updated_index = ArtifactIndex(schema_version=1, artifacts=[*artifacts, artifact])
            import yaml

            atomic_write(
                index_path,
                yaml.safe_dump(updated_index.model_dump(mode="json"), sort_keys=False),
                root=self._root,
            )
        except Exception as error:  # noqa: BLE001 - local persistence boundary
            rollback_errors: list[str] = []
            for target, previous, label in (
                (path, old_report, "report"),
                (index_path, old_index, "artifact index"),
            ):
                try:
                    if previous is None:
                        if target.exists():
                            target.unlink()
                    else:
                        atomic_write(target, previous.decode("utf-8"), root=self._root)
                except Exception as rollback_error:  # noqa: BLE001
                    rollback_errors.append(
                        f"{label} rollback failed: {_safe_remote_error(rollback_error)}"
                    )
            detail = "; ".join(rollback_errors)
            message = "unable to write reconciliation report and artifact index"
            if detail:
                message += f" ({detail})"
            raise InvalidControlRoom(message) from error
        return report_with_path


def _action_record(action: ProvisionAction) -> ReconciliationAction:
    return ReconciliationAction(
        resource=action.resource,
        stable_key=action.stable_key,
        action=action.action,
        remote_id=action.remote_id,
        payload=action.payload,
    )


def _reconcile_plan(plan: ProvisioningPlan, remote: RemoteGitHubState) -> str | None:
    if remote.owner != plan.project.payload.get(
        "owner"
    ) or remote.repository != plan.project.payload.get("repository"):
        return "post-apply owner or repository identity mismatch"
    if remote.owner_id != plan.project.payload.get("owner_id"):
        return "post-apply owner identity ID mismatch"
    if remote.repository_id != plan.project.payload.get("repository_id"):
        return "post-apply repository identity ID mismatch"
    expected_project_id = plan.project.remote_id
    if remote.project is None or remote.project.name != plan.project.payload["name"]:
        return "post-apply project identity mismatch"
    if expected_project_id is not None and remote.project.id != expected_project_id:
        return "post-apply project node ID mismatch"
    issues = {issue.task_id for issue in remote.issues}
    missing_issues = [
        action.stable_key for action in plan.issue_actions if action.stable_key not in issues
    ]
    if missing_issues:
        return f"post-apply issues missing stable IDs: {', '.join(sorted(missing_issues))}"
    fields = {field.name: field for field in remote.fields}
    for action in plan.field_actions:
        field = fields.get(action.stable_key)
        if field is None:
            return f"post-apply field mismatch: {action.stable_key}"
        if field.data_type != action.payload.get("data_type"):
            return f"post-apply field type mismatch: {action.stable_key}"
        if tuple(option.name for option in field.options) != tuple(action.payload["options"]):
            return f"post-apply field options mismatch: {action.stable_key}"
        expected_options = action.payload.get("option_ids", {})
        if (
            isinstance(expected_options, dict)
            and expected_options
            and {option.name: option.id for option in field.options} != expected_options
        ):
            return f"post-apply field option IDs mismatch: {action.stable_key}"
    items = {item.task_id for item in remote.items}
    missing_items = [
        action.stable_key for action in plan.item_actions if action.stable_key not in items
    ]
    if missing_items:
        return f"post-apply items missing stable IDs: {', '.join(sorted(missing_items))}"
    item_by_task = {item.task_id: item for item in remote.items}
    field_by_name = {field.name: field for field in remote.fields}
    for action in plan.field_value_actions:
        task_id = str(action.payload.get("task_id"))
        field_name = str(action.payload.get("field"))
        item = item_by_task.get(task_id)
        field = field_by_name.get(field_name)
        if item is None or field is None:
            return f"post-apply field value dependency missing: {action.stable_key}"
        value = next((entry for entry in item.field_values if entry.field_id == field.id), None)
        if value is None or value.value != action.payload.get("logical_value"):
            return f"post-apply field value mismatch: {action.stable_key}"
        if value.field_type != action.payload.get("field_type"):
            return f"post-apply field value type mismatch: {action.stable_key}"
        expected_option_id = action.payload.get("option_id")
        if expected_option_id is not None and value.option_id != expected_option_id:
            return f"post-apply field value option mismatch: {action.stable_key}"
    views = {view.name: view for view in remote.views}
    for action in plan.view_actions:
        view = views.get(action.stable_key)
        if view is None:
            return f"post-apply views missing: {action.stable_key}"
        for key, remote_key in (
            ("layout", "layout"),
            ("group_by", "group_by"),
            ("sort_by", "sort_by"),
            ("filter", "filter"),
        ):
            if getattr(view, remote_key) != action.payload.get(key):
                return f"post-apply view {key} mismatch: {action.stable_key}"
    return None


def _validate_mutation_identity(operation: str, response: object, action: ProvisionAction) -> None:
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise InvalidControlRoom("GitHub mutation response is malformed")
    current: object = response["data"]
    for key in _MUTATION_RESPONSE_PATHS[operation][:-1]:
        if not isinstance(current, dict) or key not in current:
            raise InvalidControlRoom("GitHub mutation response path is malformed")
        current = current[key]
    if not isinstance(current, dict):
        raise InvalidControlRoom("GitHub mutation response object is malformed")
    returned_id = current.get("id")
    if not isinstance(returned_id, str) or not re.fullmatch(r"^[A-Za-z0-9_:-]+$", returned_id):
        raise InvalidControlRoom("GitHub mutation response identity is malformed")
    if action.remote_id is not None and returned_id != action.remote_id:
        raise InvalidControlRoom("GitHub mutation returned an unexpected object identity")
    for key in ("title", "name"):
        expected = action.payload.get(key)
        if expected is not None and key in current and current[key] != expected:
            raise InvalidControlRoom(f"GitHub mutation returned mismatched {key}")


def _status_label(status: object) -> str:
    return {
        "planned": "Inbox",
        "ready": "Ready",
        "in-progress": "In progress",
        "blocked": "Blocked",
        "done": "Done",
    }.get(str(status), "Inbox")


def _field_data_type(name: str) -> str:
    if name in {"Status", "Priority", "Day", "Phase", "Workstream", "Type", "Risk", "Evidence"}:
        return "SINGLE_SELECT"
    if name == "Target date":
        return "DATE"
    return "TEXT"


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


def _discovery_page(
    response: dict[str, object],
) -> tuple[list[object], tuple[bool, object], tuple[bool, object], dict[str, object] | None]:
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
    repository = data.get("repository")
    if repository is None:
        return nodes, (has_next, cursor), (False, None), None
    if not isinstance(repository, dict):
        raise InvalidControlRoom("GitHub discovery repository connection is malformed")
    issues = repository.get("issues")
    if not isinstance(issues, dict):
        raise InvalidControlRoom("GitHub discovery repository issues connection is malformed")
    issue_nodes = issues.get("nodes")
    issue_info = issues.get("pageInfo")
    if not isinstance(issue_nodes, list) or not isinstance(issue_info, dict):
        raise InvalidControlRoom("GitHub discovery repository issues page is malformed")
    issue_has_next = issue_info.get("hasNextPage")
    issue_cursor = issue_info.get("endCursor")
    if not isinstance(issue_has_next, bool):
        raise InvalidControlRoom("GitHub discovery issue pageInfo is malformed")
    return nodes, (has_next, cursor), (issue_has_next, issue_cursor), repository


def _parse_discovered_project(
    raw: dict[str, object],
    *,
    owner: str,
    repository: str,
    repository_raw: dict[str, object] | None,
    owner_id: str | None,
    repository_issue_nodes: list[object],
) -> RemoteGitHubState:
    project_id = raw.get("id")
    number = raw.get("number")
    name = raw.get("title", raw.get("name"))
    url = raw.get("url")
    if not all(isinstance(value, str) and value for value in (project_id, name, url)):
        raise InvalidControlRoom("GitHub discovery project identity is malformed")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise InvalidControlRoom("GitHub discovery project number is malformed")
    fields_raw = raw.get("fields")
    items_raw = raw.get("items")
    views_raw = raw.get("views")
    if (
        not isinstance(fields_raw, dict)
        or not isinstance(items_raw, dict)
        or not isinstance(views_raw, dict)
    ):
        raise InvalidControlRoom("GitHub discovery fields or items are malformed")
    field_nodes = fields_raw.get("nodes")
    field_page_info = fields_raw.get("pageInfo")
    item_nodes = items_raw.get("nodes")
    item_page_info = items_raw.get("pageInfo")
    if (
        not isinstance(field_nodes, list)
        or not isinstance(field_page_info, dict)
        or not isinstance(item_nodes, list)
        or not isinstance(item_page_info, dict)
    ):
        raise InvalidControlRoom("GitHub discovery fields or items nodes are malformed")
    if not isinstance(field_page_info.get("hasNextPage"), bool):
        raise InvalidControlRoom("GitHub discovery field pageInfo is malformed")
    if field_page_info["hasNextPage"] and not isinstance(field_page_info.get("endCursor"), str):
        raise InvalidControlRoom("GitHub discovery field pageInfo hasNextPage without cursor")
    if not isinstance(item_page_info.get("hasNextPage"), bool):
        raise InvalidControlRoom("GitHub discovery item pageInfo is malformed")
    if item_page_info["hasNextPage"] and not isinstance(item_page_info.get("endCursor"), str):
        raise InvalidControlRoom("GitHub discovery item pageInfo hasNextPage without cursor")
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
        if isinstance(options, dict):
            options = options.get("nodes")
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
        fields.append(
            RemoteField(
                id=field["id"],
                name=field["name"],
                data_type=field.get("dataType"),
                options=tuple(
                    RemoteOption(id=option["id"], name=option["name"]) for option in options
                ),
            )
        )
    issues: list[RemoteIssue] = []
    items: list[RemoteProjectItem] = []
    field_by_name = {field.name: field for field in fields}
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
        values_raw = item.get("fieldValues")
        if (
            not isinstance(values_raw, dict)
            or not isinstance(values_raw.get("nodes"), list)
            or not isinstance(values_raw.get("pageInfo"), dict)
        ):
            raise InvalidControlRoom("GitHub discovery item field values are malformed")
        value_page_info = values_raw["pageInfo"]
        if not isinstance(value_page_info.get("hasNextPage"), bool):
            raise InvalidControlRoom("GitHub discovery field value pageInfo is malformed")
        if value_page_info["hasNextPage"] and not isinstance(value_page_info.get("endCursor"), str):
            raise InvalidControlRoom(
                "GitHub discovery field value pageInfo hasNextPage without cursor"
            )
        field_values: list[RemoteFieldValue] = []
        for value in values_raw["nodes"]:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise InvalidControlRoom("GitHub discovery field value is malformed")
            field_ref = value.get("field")
            if (
                not isinstance(field_ref, dict)
                or not isinstance(field_ref.get("id"), str)
                or not isinstance(field_ref.get("name"), str)
            ):
                raise InvalidControlRoom("GitHub discovery field value field is malformed")
            populated = [
                (key, value.get(key))
                for key in ("name", "text", "number", "date")
                if value.get(key) is not None
            ]
            if len(populated) != 1 or any(
                existing.field_id == field_ref["id"] for existing in field_values
            ):
                raise InvalidControlRoom("GitHub discovery field value has malformed shape")
            kind, raw_value = populated[0]
            typed = {
                "name": {
                    "field_type": "single-select",
                    "option_name": raw_value,
                    "option_id": value.get("optionId")
                    or next(
                        (
                            option.id
                            for option in (
                                field_by_name[field_ref["name"]].options
                                if field_ref["name"] in field_by_name
                                else ()
                            )
                            if option.name == raw_value
                        ),
                        None,
                    ),
                },
                "text": {"field_type": "text", "text": raw_value},
                "number": {"field_type": "number", "number": raw_value},
                "date": {"field_type": "date", "date": raw_value},
            }[kind]
            field_values.append(RemoteFieldValue(id=value["id"], field_id=field_ref["id"], **typed))
        items.append(RemoteProjectItem(id=item["id"], task_id=task_id, field_values=field_values))
    views_nodes = views_raw.get("nodes")
    views_page_info = views_raw.get("pageInfo")
    if not isinstance(views_nodes, list) or not isinstance(views_page_info, dict):
        raise InvalidControlRoom("GitHub discovery views are malformed")
    if not isinstance(views_page_info.get("hasNextPage"), bool):
        raise InvalidControlRoom("GitHub discovery view pageInfo is malformed")
    if views_page_info["hasNextPage"] and not isinstance(views_page_info.get("endCursor"), str):
        raise InvalidControlRoom("GitHub discovery view pageInfo hasNextPage without cursor")
    views: list[RemoteView] = []
    for view in views_nodes:
        if (
            not isinstance(view, dict)
            or not isinstance(view.get("id"), str)
            or not isinstance(view.get("name"), str)
        ):
            raise InvalidControlRoom("GitHub discovery contains a malformed view")
        views.append(
            RemoteView(
                id=view["id"],
                name=view["name"],
                layout=view.get("layout"),
                group_by=view.get("groupBy", view.get("group_by")),
                sort_by=view.get("sortBy", view.get("sort_by")),
                filter=view.get("filter"),
            )
        )
    standalone_raw = repository_raw.get("issues") if repository_raw is not None else None
    standalone_nodes = repository_issue_nodes
    standalone_page_info = (
        standalone_raw.get("pageInfo") if isinstance(standalone_raw, dict) else None
    )
    if not isinstance(standalone_nodes, list) or not isinstance(standalone_page_info, dict):
        raise InvalidControlRoom("GitHub discovery repository issues are malformed")
    if not isinstance(standalone_page_info.get("hasNextPage"), bool):
        raise InvalidControlRoom("GitHub discovery issue pageInfo is malformed")
    if standalone_page_info["hasNextPage"] and not isinstance(
        standalone_page_info.get("endCursor"), str
    ):
        raise InvalidControlRoom("GitHub discovery issue pageInfo hasNextPage without cursor")
    known_tasks = {issue.task_id for issue in issues}
    for raw_issue in standalone_nodes:
        if not isinstance(raw_issue, dict):
            raise InvalidControlRoom("GitHub discovery repository issue is malformed")
        issue_repo = raw_issue.get("repository")
        if not isinstance(issue_repo, dict) or issue_repo.get("nameWithOwner") != repository:
            raise InvalidControlRoom(
                "GitHub discovery issue repository does not match configuration"
            )
        issue_id = raw_issue.get("id")
        issue_number = raw_issue.get("number")
        issue_title = raw_issue.get("title")
        issue_url = raw_issue.get("url")
        body = raw_issue.get("body")
        if (
            not isinstance(issue_id, str)
            or not isinstance(issue_number, int)
            or issue_number < 1
            or not isinstance(issue_title, str)
            or not isinstance(issue_url, str)
            or not isinstance(body, str)
        ):
            raise InvalidControlRoom("GitHub discovery repository issue is malformed")
        task_id = extract_task_id(body)
        if task_id in known_tasks:
            existing = next(issue for issue in issues if issue.task_id == task_id)
            if existing.node_id != issue_id or existing.number != issue_number:
                raise InvalidControlRoom(
                    f"GitHub discovery contains conflicting issue identity for {task_id}"
                )
            continue
        known_tasks.add(task_id)
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
    return RemoteGitHubState(
        owner=owner,
        repository=repository,
        owner_id=owner_id,
        repository_id=repository_raw.get("id")
        if isinstance(repository_raw.get("id"), str)
        else None,
        project=RemoteProject(id=project_id, number=number, name=name, url=url),
        issues=tuple(issues),
        fields=tuple(fields),
        items=tuple(items),
        views=tuple(views),
    )


class GitHubClient:
    def __init__(self, transport: GhTransport) -> None:
        self._transport = transport

    def _connection_pages(
        self,
        query: str,
        node_id: str,
        connection: str,
        initial_nodes: list[object],
        initial_page: dict[str, object],
    ) -> list[object]:
        """Fetch every nested page and reject malformed or cyclic cursors."""
        nodes = list(initial_nodes)
        page = initial_page
        seen_cursors: set[str] = set()
        seen_nodes: set[str] = {
            value["id"]
            for value in nodes
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        }
        while True:
            has_next = page.get("hasNextPage")
            cursor = page.get("endCursor")
            if not isinstance(has_next, bool):
                raise InvalidControlRoom(f"GitHub discovery {connection} pageInfo is malformed")
            if not has_next:
                return nodes
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise InvalidControlRoom(
                    f"GitHub discovery {connection} cursor cycle or missing cursor"
                )
            seen_cursors.add(cursor)
            response = self._transport.graphql(query, {"id": node_id, "after": cursor})
            if not isinstance(response, dict) or response.get("errors"):
                raise DependencyUnavailable("GitHub discovery failed")
            data = response.get("data")
            node = data.get("node") if isinstance(data, dict) else None
            connection_data = node.get(connection) if isinstance(node, dict) else None
            if (
                not isinstance(connection_data, dict)
                or not isinstance(connection_data.get("nodes"), list)
                or not isinstance(connection_data.get("pageInfo"), dict)
            ):
                raise InvalidControlRoom(f"GitHub discovery nested {connection} page is malformed")
            for value in connection_data["nodes"]:
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    if value["id"] in seen_nodes:
                        raise InvalidControlRoom(
                            f"GitHub discovery duplicate nested {connection} node"
                        )
                    seen_nodes.add(value["id"])
                nodes.append(value)
            page = connection_data["pageInfo"]

    def _expand_discovered_project(self, raw: dict[str, object]) -> dict[str, object]:
        expanded = dict(raw)
        project_id = raw.get("id")
        if not isinstance(project_id, str):
            raise InvalidControlRoom("GitHub discovery project identity is malformed")
        for key, query in (
            ("fields", _NESTED_FIELDS_QUERY),
            ("views", _NESTED_VIEWS_QUERY),
            ("items", _NESTED_ITEMS_QUERY),
        ):
            connection = raw.get(key)
            if (
                not isinstance(connection, dict)
                or not isinstance(connection.get("nodes"), list)
                or not isinstance(connection.get("pageInfo"), dict)
            ):
                raise InvalidControlRoom(f"GitHub discovery {key} connection is malformed")
            expanded[key] = dict(connection)
            expanded[key]["nodes"] = self._connection_pages(
                query, project_id, key, connection["nodes"], connection["pageInfo"]
            )
        # Field options have their own connection and must be paginated independently.
        field_nodes = []
        for field in expanded["fields"]["nodes"]:
            if not isinstance(field, dict):
                raise InvalidControlRoom("GitHub discovery field is malformed")
            options = field.get("options", [])
            if isinstance(options, dict):
                if not isinstance(options.get("nodes"), list) or not isinstance(
                    options.get("pageInfo"), dict
                ):
                    raise InvalidControlRoom(
                        "GitHub discovery field options connection is malformed"
                    )
                field = dict(field)
                field["options"] = self._connection_pages(
                    _NESTED_OPTIONS_QUERY,
                    str(field["id"]),
                    "options",
                    options["nodes"],
                    options["pageInfo"],
                )
            field_nodes.append(field)
        expanded["fields"]["nodes"] = field_nodes
        # Each item has an independently paginated field-value connection.
        expanded_items = []
        for item in expanded["items"]["nodes"]:
            if not isinstance(item, dict):
                raise InvalidControlRoom("GitHub discovery item is malformed")
            values = item.get("fieldValues")
            if (
                not isinstance(values, dict)
                or not isinstance(values.get("nodes"), list)
                or not isinstance(values.get("pageInfo"), dict)
            ):
                raise InvalidControlRoom(
                    "GitHub discovery item field values connection is malformed"
                )
            item = dict(item)
            item["fieldValues"] = dict(values)
            item["fieldValues"]["nodes"] = self._connection_pages(
                _NESTED_ITEM_VALUES_QUERY,
                str(item["id"]),
                "fieldValues",
                values["nodes"],
                values["pageInfo"],
            )
            expanded_items.append(item)
        expanded["items"]["nodes"] = expanded_items
        return expanded

    def discover_state(self, owner: str, repository: str, project_name: str) -> RemoteGitHubState:
        """Discover a named project with read-only, strict, paginated requests."""
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidControlRoom("GitHub project owner must not be empty")
        if not isinstance(project_name, str) or not project_name.strip():
            raise InvalidControlRoom("GitHub project name must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise InvalidControlRoom("GitHub repository must be canonical owner/name")
        after: str | None = None
        issues_after: str | None = None
        project_cursors: set[str] = set()
        issue_cursors: set[str] = set()
        matches: list[dict[str, object]] = []
        repository_raw: dict[str, object] | None = None
        owner_id: str | None = None
        repository_issue_nodes: list[object] = []
        while True:
            try:
                response = self._transport.graphql(
                    _DISCOVERY_QUERY,
                    {
                        "owner": owner,
                        "repository_name": repository.split("/", 1)[1],
                        "after": after,
                        "issues_after": issues_after,
                    },
                )
            except StopIteration as error:
                raise InvalidControlRoom("GitHub discovery ended during pagination") from error
            if not isinstance(response, dict):
                raise InvalidControlRoom("GitHub discovery returned a non-object response")
            if response.get("errors"):
                raise DependencyUnavailable("GitHub discovery failed")
            projects, page_info, issue_page_info, current_repository = _discovery_page(response)
            user = (
                response.get("data", {}).get("user")
                if isinstance(response.get("data"), dict)
                else None
            )
            if isinstance(user, dict) and isinstance(user.get("id"), str):
                owner_id = user["id"]
            if current_repository is not None:
                repository_raw = current_repository
                issues_connection = current_repository.get("issues")
                if isinstance(issues_connection, dict) and isinstance(
                    issues_connection.get("nodes"), list
                ):
                    repository_issue_nodes.extend(issues_connection["nodes"])
            for raw in projects:
                if not isinstance(raw, dict):
                    raise InvalidControlRoom("GitHub discovery contains a malformed project")
                name = raw.get("title", raw.get("name"))
                if name == project_name:
                    matches.append(raw)
            if not page_info[0] and not issue_page_info[0]:
                break
            if page_info[0]:
                cursor = page_info[1]
                if not isinstance(cursor, str) or not cursor:
                    raise InvalidControlRoom(
                        "GitHub discovery hasNextPage without a project cursor"
                    )
                after = cursor
            if issue_page_info[0]:
                cursor = issue_page_info[1]
                if not isinstance(cursor, str) or not cursor:
                    raise InvalidControlRoom("GitHub discovery hasNextPage without an issue cursor")
                issues_after = cursor
            if page_info[0]:
                cursor = page_info[1]
                if cursor in project_cursors:
                    raise InvalidControlRoom("GitHub discovery cursor cycle detected")
                project_cursors.add(cursor)
            if issue_page_info[0]:
                cursor = issue_page_info[1]
                if cursor in issue_cursors:
                    raise InvalidControlRoom("GitHub discovery cursor cycle detected")
                issue_cursors.add(cursor)
        if len(matches) > 1:
            raise InvalidControlRoom(f"GitHub project name is ambiguous: {project_name}")
        if not matches:
            if repository_raw is None:
                raise InvalidControlRoom("GitHub discovery response is missing repository issues")
            standalone: list[RemoteIssue] = []
            seen_standalone: set[str] = set()
            for raw_issue in repository_issue_nodes:
                if not isinstance(raw_issue, dict):
                    raise InvalidControlRoom("GitHub discovery repository issue is malformed")
                issue_id, number, title, url, body = (
                    raw_issue.get("id"),
                    raw_issue.get("number"),
                    raw_issue.get("title"),
                    raw_issue.get("url"),
                    raw_issue.get("body"),
                )
                if (
                    not isinstance(issue_id, str)
                    or not isinstance(number, int)
                    or number < 1
                    or not isinstance(title, str)
                    or not isinstance(url, str)
                    or not isinstance(body, str)
                ):
                    raise InvalidControlRoom("GitHub discovery repository issue is malformed")
                issue_repo = raw_issue.get("repository")
                if (
                    not isinstance(issue_repo, dict)
                    or issue_repo.get("nameWithOwner") != repository
                ):
                    raise InvalidControlRoom(
                        "GitHub discovery issue repository does not match configuration"
                    )
                task_id = extract_task_id(body)
                if task_id in seen_standalone:
                    raise InvalidControlRoom(
                        f"GitHub discovery contains duplicate stable task ID: {task_id}"
                    )
                seen_standalone.add(task_id)
                standalone.append(
                    RemoteIssue(
                        task_id=task_id,
                        node_id=issue_id,
                        number=number,
                        url=url,
                        title=title,
                        body=body,
                    )
                )
            return RemoteGitHubState(
                owner=owner,
                repository=repository,
                owner_id=owner_id,
                repository_id=repository_raw.get("id")
                if isinstance(repository_raw.get("id"), str)
                else None,
                issues=tuple(standalone),
            )
        return _parse_discovered_project(
            self._expand_discovered_project(matches[0]),
            owner=owner,
            repository=repository,
            repository_raw=repository_raw,
            owner_id=owner_id,
            repository_issue_nodes=repository_issue_nodes,
        )

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
