from __future__ import annotations

import json
import subprocess

import pytest

from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.github import (
    GitHubClient,
    SubprocessGhTransport,
    extract_task_id,
)


class FakeTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((query, variables))
        return next(self.responses)


def project_response(
    *, cursor: str | None = None, has_next: bool = False, items=None, field_definitions=None
):
    response = {
        "data": {
            "user": {
                "projectV2": {
                    "id": "PVT_1",
                    "title": "AgentOps Research Control Plane — 14-Day v0.1",
                    "url": "https://github.com/users/Ven-Z8/projects/1",
                    "fields": {"nodes": field_definitions or []},
                    "items": {
                        "nodes": items or [],
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    },
                }
            }
        }
    }
    if field_definitions is None:
        control_selects = {
            "Status",
            "Priority",
            "Phase",
            "Evidence",
            "Workstream",
            "Type",
            "Risk",
        }
        control_data_types = {
            "Day": "NUMBER",
            "Harness": "TEXT",
            "Dependency": "TEXT",
            "Blocker": "TEXT",
            "Handoff": "TEXT",
        }
        discovered = {}
        for item in items or []:
            for node in item.get("fieldValues", {}).get("nodes", []):
                field = node["field"]
                name = field["name"]
                option_name = node.get("name")
                if name in discovered:
                    if name in control_selects and option_name is not None:
                        discovered[name]["options"].append(
                            {"id": f"OPT_{name}_{option_name}", "name": option_name}
                        )
                    continue
                definition = {
                    "id": field["id"],
                    "name": name,
                    "__typename": (
                        "ProjectV2SingleSelectField"
                        if name in control_selects
                        else "ProjectV2IterationField"
                        if name == "Iteration"
                        else "ProjectV2Field"
                    ),
                }
                if name not in control_selects and name != "Iteration":
                    definition["dataType"] = control_data_types.get(name, "TEXT")
                if name in control_selects and option_name is not None:
                    definition["options"] = [
                        {"id": f"OPT_{name}_{option_name}", "name": option_name}
                    ]
                discovered[name] = definition
        response["data"]["user"]["projectV2"]["fields"]["nodes"] = list(discovered.values())
    return response


def complete_control_definitions(*, missing_data_type: str | None = None):
    select_options = {
        "Status": ["Inbox", "Ready", "In progress", "Blocked", "Done"],
        "Priority": ["P0", "P1", "P2", "P3"],
        "Phase": ["Phase 1", "Phase 2"],
        "Evidence": ["Missing", "Inconclusive", "Partial", "Verified"],
        "Workstream": ["Trust", "kernel"],
        "Type": ["task", "outcome"],
        "Risk": ["Critical", "high", "medium", "low"],
    }
    definitions = []
    for name, options in select_options.items():
        definitions.append(
            {
                "id": f"PVT_FIELD_{name}",
                "name": name,
                "__typename": "ProjectV2SingleSelectField",
                "options": [{"id": f"OPT_{name}_{option}", "name": option} for option in options],
            }
        )
    for name, data_type in {
        "Day": "NUMBER",
        "Harness": "TEXT",
        "Dependency": "TEXT",
        "Blocker": "TEXT",
        "Handoff": "TEXT",
    }.items():
        definitions.append(
            {
                "id": f"PVT_FIELD_{name}",
                "name": name,
                "__typename": "ProjectV2Field",
                **({} if name == missing_data_type else {"dataType": data_type}),
            }
        )
    return definitions


def issue_item(
    task_id: str = "AO-D01-01",
    *,
    number: int = 1,
    title: str = "Capture reproducible baseline",
    fields=None,
):
    def field_value_node(index: int, field: dict[str, object]) -> dict[str, object]:
        field_data = dict(field["field"])
        name = field_data["name"]
        field_data.setdefault(
            "__typename",
            "ProjectV2SingleSelectField"
            if name in {"Status", "Priority", "Phase", "Evidence", "Workstream", "Type", "Risk"}
            else "ProjectV2IterationField"
            if name == "Iteration"
            else "ProjectV2Field",
        )
        return {
            "id": f"PVTFV_{number}_{index}",
            **field,
            "field": {
                "id": f"PVT_FIELD_{name}",
                **field_data,
            },
        }

    return {
        "id": f"PVTI_{number}",
        "content": {
            "number": number,
            "title": title,
            "url": f"https://github.com/Ven-Z8/agentops-harness/issues/{number}",
            "repository": {"nameWithOwner": "Ven-Z8/agentops-harness"},
            "body": f"Task ID: {task_id}\n",
        },
        "fieldValues": {
            "nodes": [
                field_value_node(index, field) for index, field in enumerate(fields or [], start=1)
            ]
        },
    }


PROJECT_RESPONSE = project_response(items=[issue_item()])


def test_export_is_read_only_and_maps_task_ids() -> None:
    transport = FakeTransport([PROJECT_RESPONSE])

    export = GitHubClient(transport).export_project("Ven-Z8", 1)

    assert export.items[0].task_id == "AO-D01-01"
    assert export.items[0].issue_number == 1
    assert all("mutation" not in query.lower() for query, _ in transport.calls)


def test_extract_task_id_requires_exact_stable_line() -> None:
    assert extract_task_id("Context\nTask ID: AO-D01-01\nMore") == "AO-D01-01"
    for body in (
        "Task ID: AO-D01-01 extra",
        "prefix Task ID: AO-D01-01",
        "Task ID: AO-X01",
        "",
    ):
        with pytest.raises(InvalidControlRoom, match="stable task ID"):
            extract_task_id(body)


def test_export_maps_supported_project_fields() -> None:
    fields = [
        {"field": {"name": "Status"}, "name": "Blocked"},
        {"field": {"name": "Priority"}, "name": "P1"},
        {"field": {"name": "Day"}, "number": 2},
        {"field": {"name": "Phase"}, "name": "Phase 1"},
        {"field": {"name": "Evidence"}, "name": "Verified"},
        {"field": {"name": "Harness"}, "text": "codex"},
        {"field": {"name": "Dependency"}, "text": "AO-D01-01"},
        {"field": {"name": "Blocker"}, "text": "waiting on approval"},
        {"field": {"name": "Handoff"}, "text": "coordination/handoffs/x.md"},
    ]
    response = project_response(items=[issue_item(fields=fields)])

    item = GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1).items[0]

    assert item.status == "blocked"
    assert item.priority == "P1"
    assert item.day == 2
    assert item.phase_id == "AO-P1"
    assert item.evidence == "verified"
    assert item.harness == "codex"
    assert item.dependency == "AO-D01-01"
    assert item.blocker == "waiting on approval"
    assert item.handoff == "coordination/handoffs/x.md"


def test_export_fetches_all_pages_and_advances_cursor() -> None:
    first = project_response(cursor="CURSOR_1", has_next=True, items=[issue_item()])
    second = project_response(
        cursor=None,
        has_next=False,
        items=[issue_item("AO-D01-02", number=2, title="Separate statuses")],
    )
    transport = FakeTransport([first, second])

    export = GitHubClient(transport).export_project("Ven-Z8", 1)

    assert [item.task_id for item in export.items] == ["AO-D01-01", "AO-D01-02"]
    assert transport.calls[0][1]["after"] is None
    assert transport.calls[1][1]["after"] == "CURSOR_1"


@pytest.mark.parametrize(
    "response",
    [
        project_response(cursor="CURSOR_1", has_next=True, items=[issue_item()]),
        {"errors": [{"message": "forbidden"}]},
        {"data": {"user": {"projectV2": None}}},
        project_response(items=[{**issue_item(), "content": None}]),
        project_response(items=[issue_item(), issue_item()]),
    ],
)
def test_export_rejects_invalid_or_incomplete_graphql_state(response) -> None:
    responses = [response]
    project = response.get("data", {}).get("user", {}).get("projectV2")
    if isinstance(project, dict) and project.get("items", {}).get("pageInfo", {}).get(
        "hasNextPage"
    ):
        responses.append(project_response(cursor="CURSOR_1", has_next=True, items=[]))

    with pytest.raises(InvalidControlRoom):
        GitHubClient(FakeTransport(responses)).export_project("Ven-Z8", 1)


def test_export_rejects_cursor_cycle_and_has_next_without_cursor() -> None:
    cycle = [
        project_response(cursor="CURSOR_1", has_next=True, items=[issue_item()]),
        project_response(
            cursor="CURSOR_1", has_next=True, items=[issue_item("AO-D01-02", number=2)]
        ),
    ]
    missing = project_response(cursor=None, has_next=True, items=[issue_item()])

    for responses in (cycle, [missing]):
        with pytest.raises(InvalidControlRoom, match="cursor"):
            GitHubClient(FakeTransport(responses)).export_project("Ven-Z8", 1)


def test_export_rejects_bad_urls_and_unsupported_field_values() -> None:
    bad_url = project_response(items=[issue_item()])
    bad_url["data"]["user"]["projectV2"]["url"] = "https://github.com/project\nforged"
    unsupported = project_response(
        items=[issue_item(fields=[{"field": {"name": "Day"}, "text": "2"}])]
    )

    for response in (bad_url, unsupported):
        with pytest.raises(InvalidControlRoom):
            GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_subprocess_transport_uses_read_only_argument_array_and_json_stdin(monkeypatch) -> None:
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(args, 0, '{"data": {}}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SubprocessGhTransport().graphql(
        "query Project($x: Int!) { viewer { login } }", {"x": 1}
    )

    assert result == {"data": {}}
    assert captured["args"] == ["gh", "api", "graphql", "--input", "-"]
    assert captured["kwargs"]["input"] == json.dumps(
        {"query": "query Project($x: Int!) { viewer { login } }", "variables": {"x": 1}}
    )
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False


def test_subprocess_transport_refuses_mutation_text_without_invoking_gh(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("gh must not run for a mutation query"),
    )

    with pytest.raises(InvalidControlRoom, match="read-only"):
        SubprocessGhTransport().graphql("mutation { deleteProject }", {})


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("data", "user", "projectV2", "items", "pageInfo", "hasNextPage"), "false"),
        (("data", "user", "projectV2", "items", "nodes", 0, "content", "number"), "1"),
        (("data", "user", "projectV2", "items", "nodes", 0, "id"), 1),
        (
            ("data", "user", "projectV2", "items", "nodes", 0, "fieldValues", "nodes", 0, "number"),
            True,
        ),
    ],
)
def test_export_rejects_graphql_scalar_type_substitution(path, value) -> None:
    response = project_response(
        items=[issue_item(fields=[{"field": {"name": "Day"}, "number": 2}])]
    )
    target = response
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(InvalidControlRoom, match="schema"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_rejects_unknown_custom_definition_and_allows_known_builtin() -> None:
    unknown = project_response(items=[issue_item()])
    unknown["data"]["user"]["projectV2"]["fields"] = {
        "nodes": [
            {
                "id": "F_UNKNOWN",
                "name": "Mystery",
                "__typename": "ProjectV2Field",
                "dataType": "TEXT",
            }
        ]
    }
    with pytest.raises(InvalidControlRoom, match="unknown field"):
        GitHubClient(FakeTransport([unknown])).export_project("Ven-Z8", 1)

    builtin = project_response(items=[issue_item()])
    builtin["data"]["user"]["projectV2"]["fields"] = {
        "nodes": [
            {
                "id": "F_LABELS",
                "name": "Labels",
                "__typename": "ProjectV2Field",
                "dataType": "LABELS",
            }
        ]
    }
    assert GitHubClient(FakeTransport([builtin])).export_project("Ven-Z8", 1).items


def test_export_rejects_missing_duplicate_option_ids_and_empty_option_value() -> None:
    for options in (
        [{"name": "P0"}],
        [{"id": "O1", "name": "P0"}, {"id": "O1", "name": "P1"}],
        [{"id": "O1", "name": "P0"}, {"id": "O2", "name": "P0"}],
    ):
        response = project_response(
            items=[issue_item(fields=[{"field": {"name": "Priority"}, "name": "P0"}])]
        )
        response["data"]["user"]["projectV2"]["fields"] = {
            "nodes": [
                {
                    "id": "F_PRIORITY",
                    "name": "Priority",
                    "__typename": "ProjectV2SingleSelectField",
                    "options": options,
                }
            ]
        }
        with pytest.raises(InvalidControlRoom):
            GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_rejects_wrong_definition_type() -> None:
    response = project_response(
        items=[issue_item(fields=[{"field": {"name": "Priority"}, "name": "P0"}])]
    )
    response["data"]["user"]["projectV2"]["fields"] = {
        "nodes": [
            {
                "id": "F_PRIORITY",
                "name": "Priority",
                "__typename": "ProjectV2Field",
                "dataType": "TEXT",
            }
        ]
    }
    with pytest.raises(InvalidControlRoom, match="type"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/Ven-Z8/agentops-harness/issues/1",
        "https://github.com/Ven-Z8/agentops-harness/issues/2",
        "https://github.com/Ven-Z8/agentops-harness/issues/1?x=1",
        "https://github.com/Ven-Z8/agentops-harness/issues/1#fragment",
    ],
)
def test_export_rejects_noncanonical_issue_url(url: str) -> None:
    response = project_response(items=[issue_item()])
    response["data"]["user"]["projectV2"]["items"]["nodes"][0]["content"]["url"] = url
    with pytest.raises(InvalidControlRoom, match="canonical"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_accepts_canonical_issue_url() -> None:
    export = GitHubClient(FakeTransport([PROJECT_RESPONSE])).export_project("Ven-Z8", 1)
    assert export.repository == "Ven-Z8/agentops-harness"


def test_iteration_builtin_definition_and_value_are_ignored() -> None:
    fields = [
        {
            "field": {"id": "F_ITERATION", "name": "Iteration"},
            "iterationId": "IT_1",
            "title": "Week 1",
        }
    ]
    response = project_response(
        items=[issue_item(fields=fields)],
        field_definitions=[
            {"id": "F_ITERATION", "name": "Iteration", "__typename": "ProjectV2IterationField"}
        ],
    )

    export = GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)

    assert export.items[0].task_id == "AO-D01-01"


@pytest.mark.parametrize(
    "fields",
    [
        [{"field": {"name": "Iteration"}, "title": "Week 1"}],
        [{"field": {"id": "WRONG", "name": "Iteration"}, "iterationId": "IT_1", "title": "Week 1"}],
    ],
)
def test_iteration_value_must_have_correlated_identity(fields) -> None:
    response = project_response(
        items=[issue_item(fields=fields)],
        field_definitions=[
            {"id": "F_ITERATION", "name": "Iteration", "__typename": "ProjectV2IterationField"}
        ],
    )

    with pytest.raises(InvalidControlRoom):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_rejects_duplicate_definition_and_field_value_ids() -> None:
    duplicate_definition_ids = project_response(items=[issue_item()])
    duplicate_definition_ids["data"]["user"]["projectV2"]["fields"] = {
        "nodes": [
            {"id": "F_DUP", "name": "Status", "__typename": "ProjectV2SingleSelectField"},
            {"id": "F_DUP", "name": "Priority", "__typename": "ProjectV2SingleSelectField"},
        ]
    }
    with pytest.raises(InvalidControlRoom, match="definition ID"):
        GitHubClient(FakeTransport([duplicate_definition_ids])).export_project("Ven-Z8", 1)

    item = issue_item(fields=[{"field": {"name": "Status"}, "name": "Ready"}])
    item["fieldValues"]["nodes"][0]["id"] = "DUP"
    item["fieldValues"]["nodes"].append(dict(item["fieldValues"]["nodes"][0]))
    duplicate_value_ids = project_response(
        items=[item], field_definitions=complete_control_definitions()
    )
    with pytest.raises(InvalidControlRoom, match="field value ID"):
        GitHubClient(FakeTransport([duplicate_value_ids])).export_project("Ven-Z8", 1)


def test_export_rejects_field_value_id_name_mismatch() -> None:
    item = issue_item(fields=[{"field": {"name": "Status"}, "name": "Ready"}])
    item["fieldValues"]["nodes"][0]["field"]["id"] = "OTHER"
    response = project_response(items=[item], field_definitions=complete_control_definitions())
    response["data"]["user"]["projectV2"]["fields"]["nodes"][0]["id"] = "OTHER_DEF"
    with pytest.raises(InvalidControlRoom, match="definition"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_accepts_only_graphql_typename_alias() -> None:
    response = project_response(items=[issue_item()])
    response["data"]["user"]["projectV2"]["fields"] = {
        "nodes": [{"id": "F_STATUS", "name": "Status", "typename": "ProjectV2SingleSelectField"}]
    }
    with pytest.raises(InvalidControlRoom, match="schema"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


@pytest.mark.parametrize("day", [float("nan"), float("inf"), float("-inf"), True, 2.5, 0, 15])
def test_export_rejects_unsafe_day_numbers(day) -> None:
    response = project_response(
        items=[issue_item(fields=[{"field": {"name": "Day"}, "number": day}])],
        field_definitions=complete_control_definitions(),
    )
    with pytest.raises(InvalidControlRoom):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


def test_export_accepts_integral_day_number() -> None:
    response = project_response(
        items=[issue_item(fields=[{"field": {"name": "Day"}, "number": 2.0}])],
        field_definitions=complete_control_definitions(),
    )
    assert GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1).items[0].day == 2


@pytest.mark.parametrize("name", ["Day", "Harness", "Dependency", "Blocker", "Handoff"])
def test_export_requires_data_type_for_project_field(name: str) -> None:
    response = project_response(
        items=[issue_item()], field_definitions=complete_control_definitions(missing_data_type=name)
    )
    with pytest.raises(InvalidControlRoom, match="dataType"):
        GitHubClient(FakeTransport([response])).export_project("Ven-Z8", 1)


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.CalledProcessError(1, ["gh"])])
def test_subprocess_transport_maps_missing_or_unauthenticated_gh(error, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(DependencyUnavailable):
        SubprocessGhTransport().graphql("query { viewer { login } }", {})


def test_subprocess_transport_maps_auth_failure_and_json_failure(monkeypatch) -> None:
    responses = [
        subprocess.CompletedProcess(["gh"], 1, "", "not logged in"),
        subprocess.CompletedProcess(["gh"], 0, "not json", ""),
    ]

    def fake_run(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(DependencyUnavailable):
        SubprocessGhTransport().graphql("query { viewer { login } }", {})
    with pytest.raises(InvalidControlRoom):
        SubprocessGhTransport().graphql("query { viewer { login } }", {})
