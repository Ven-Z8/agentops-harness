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


def project_response(*, cursor: str | None = None, has_next: bool = False, items=None):
    return {
        "data": {
            "user": {
                "projectV2": {
                    "id": "PVT_1",
                    "title": "AgentOps Research Control Plane — 14-Day v0.1",
                    "url": "https://github.com/users/Ven-Z8/projects/1",
                    "fields": {"nodes": []},
                    "items": {
                        "nodes": items or [],
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    },
                }
            }
        }
    }


def issue_item(
    task_id: str = "AO-D01-01",
    *,
    number: int = 1,
    title: str = "Capture reproducible baseline",
    fields=None,
):
    return {
        "id": f"PVTI_{number}",
        "content": {
            "number": number,
            "title": title,
            "url": f"https://github.com/Ven-Z8/agentops-harness/issues/{number}",
            "body": f"Task ID: {task_id}\n",
        },
        "fieldValues": {"nodes": fields or []},
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
