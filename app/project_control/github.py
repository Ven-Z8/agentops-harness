"""Read-only GitHub Projects export through an injected GraphQL transport."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.models import BoardExport, BoardItem


class GhTransport(Protocol):
    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]: ...


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _GraphQLError(_StrictResponse):
    message: str = Field(min_length=1)


class _Option(_StrictResponse):
    id: str | None = None
    name: str = Field(min_length=1)


class _FieldDefinition(_StrictResponse):
    id: str | None = None
    name: str = Field(min_length=1)
    options: list[_Option] = []


class _FieldDefinitions(_StrictResponse):
    nodes: list[_FieldDefinition]


class _PageInfo(_StrictResponse):
    hasNextPage: bool
    endCursor: str | None


class _FieldRef(_StrictResponse):
    name: str = Field(min_length=1)


class _FieldValue(_StrictResponse):
    field: _FieldRef | None = None
    name: str | None = None
    text: str | None = None
    number: int | float | None = None
    date: str | None = None
    iterationId: str | None = None
    title: str | None = None


class _FieldValues(_StrictResponse):
    nodes: list[_FieldValue]


class _Issue(_StrictResponse):
    number: int = Field(gt=0)
    title: str = Field(min_length=1)
    url: str
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
          ... on ProjectV2Field { id name }
          ... on ProjectV2SingleSelectField {
            id name options { id name }
          }
          ... on ProjectV2IterationField { id name }
        }
      }
      items(first: 100, after: $after) {
        nodes {
          id
          content {
            ... on Issue { number title url body }
          }
          fieldValues(first: 100) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2Field { name } ... on ProjectV2SingleSelectField { name } }
                name
              }
              ... on ProjectV2ItemFieldTextValue {
                field { ... on ProjectV2Field { name } ... on ProjectV2SingleSelectField { name } }
                text
              }
              ... on ProjectV2ItemFieldNumberValue {
                field { ... on ProjectV2Field { name } ... on ProjectV2SingleSelectField { name } }
                number
              }
              ... on ProjectV2ItemFieldDateValue {
                field { ... on ProjectV2Field { name } ... on ProjectV2SingleSelectField { name } }
                date
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


def _field_value(value: _FieldValue, definitions: dict[str, set[str]]) -> tuple[str, object]:
    if value.field is None or not value.field.name.strip():
        raise InvalidControlRoom("GitHub project field value is missing its field name")
    name = value.field.name
    if name not in _KNOWN_FIELDS:
        raise InvalidControlRoom(f"GitHub project contains unknown field: {name}")

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
    if definitions.get(name) and kind == "name" and field_value not in definitions[name]:
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


def _board_item(
    item: _Item,
    definitions: dict[str, set[str]],
    seen_item_ids: set[str],
    seen_task_ids: set[str],
) -> BoardItem:
    if item.id in seen_item_ids:
        raise InvalidControlRoom(f"GitHub project contains duplicate item ID: {item.id}")
    seen_item_ids.add(item.id)
    if item.content is None:
        raise InvalidControlRoom("GitHub project item has unsupported or missing content")
    task_id = extract_task_id(item.content.body)
    if task_id in seen_task_ids:
        raise InvalidControlRoom(f"GitHub project contains duplicate stable task ID: {task_id}")
    seen_task_ids.add(task_id)

    values: dict[str, object] = {}
    for field_value in item.fieldValues.nodes:
        name, value = _field_value(field_value, definitions)
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
        isinstance(day, bool) or not isinstance(day, (int, float)) or int(day) != day
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

    def export_project(self, owner: str, number: int) -> BoardExport:
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidControlRoom("GitHub project owner must not be empty")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise InvalidControlRoom("GitHub project number must be positive")

        after: str | None = None
        cursors: set[str] = set()
        seen_item_ids: set[str] = set()
        seen_task_ids: set[str] = set()
        project: _Project | None = None
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
            definitions: dict[str, set[str]] = {}
            for definition in current.fields.nodes:
                if definition.name in definitions:
                    raise InvalidControlRoom(
                        f"GitHub project has duplicate field: {definition.name}"
                    )
                definitions[definition.name] = {option.name for option in definition.options}
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
            return BoardExport(project_url=project.url, items=exported)
        except ValidationError as error:
            raise InvalidControlRoom(f"GitHub board export is invalid: {error}") from error
