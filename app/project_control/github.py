"""Read-only GitHub Projects export through an injected GraphQL transport."""

from __future__ import annotations

import json
import math
import re
import subprocess
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.models import BoardExport, BoardItem


class GhTransport(Protocol):
    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]: ...


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


class GitHubClient:
    def __init__(self, transport: GhTransport) -> None:
        self._transport = transport

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
