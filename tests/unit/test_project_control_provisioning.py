from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.project_control.errors import InvalidControlRoom
from app.project_control.github import (
    DESIRED_FIELDS,
    DESIRED_VIEWS,
    MANUAL_VIEW_INSTRUCTIONS,
    VIEW_SPECS,
    ApplyGhTransport,
    GitHubProvisioner,
    _mutation_id,
    _typed_input,
    merge_managed_issue_body,
)
from app.project_control.models import (
    ProvisionAction,
    ProvisioningPlan,
    ReconciliationReport,
    RemoteField,
    RemoteFieldValue,
    RemoteGitHubState,
    RemoteIssue,
    RemoteProject,
    RemoteView,
)
from app.project_control.roadmap import render_issue_body
from tests.helpers_project_control import make_control_room_state


def test_dry_run_performs_no_mutations() -> None:
    state = make_control_room_state()
    transport = _FakeMutationTransport()
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        owner_id="USER_1",
        repository_id="REPO_1",
    )

    plan = GitHubProvisioner(transport).plan(state, remote)

    assert plan.project.stable_key == "AgentOps Research Control Plane — 14-Day v0.1"
    assert len(plan.issue_actions) == len(state.roadmap.items)
    assert transport.calls == []


def test_existing_stable_ids_are_reused_without_duplicates() -> None:
    state = make_control_room_state()
    transport = _FakeMutationTransport()
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        project=RemoteProject(
            id="PVT_1",
            number=1,
            name="AgentOps Research Control Plane — 14-Day v0.1",
            url="https://github.com/users/Ven-Z8/projects/1",
        ),
        issues=[
            RemoteIssue(
                task_id="AO-D01-01",
                node_id="I_AO-D01-01",
                number=1,
                url="https://github.com/Ven-Z8/agentops-harness/issues/1",
            )
        ],
    )

    plan = GitHubProvisioner(transport).plan(state, remote)

    assert plan.project.action == "reuse"
    assert all(action.action == "reuse" for action in plan.issue_actions)


def test_partial_apply_returns_reconciliation_report() -> None:
    state = make_control_room_state()
    transport = _FakeMutationTransport(fail_after=3)
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        owner_id="USER_1",
        repository_id="REPO_1",
    )
    plan = GitHubProvisioner(transport).plan(state, remote)

    report = GitHubProvisioner(transport).apply(plan)

    assert report.state == "partial"
    assert report.completed_object_ids
    assert report.remaining_actions


def test_desired_schema_and_views_are_exact() -> None:
    assert tuple(DESIRED_FIELDS) == (
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
        "Handoff",
        "Target date",
    )
    assert DESIRED_FIELDS["Status"] == (
        "Inbox",
        "Ready",
        "In progress",
        "In review",
        "Blocked",
        "Done",
    )
    assert DESIRED_VIEWS == ("Inbox", "Kanban", "Phase", "Harness", "Trust Blockers", "Roadmap")


def test_round2_field_value_inputs_are_typed_and_day_is_single_select() -> None:
    cases = (
        (
            "single-select",
            {"logical_value": "Day 1", "option_id": "OPT_DAY"},
            "singleSelectOptionId",
        ),
        ("text", {"logical_value": "codex"}, "text"),
        ("number", {"logical_value": 3}, "number"),
        ("date", {"logical_value": "2026-09-01"}, "date"),
    )
    for field_type, value, key in cases:
        payload = _typed_input(
            "set_field_value",
            {"project_id": "P", "item_id": "I", "field_id": "F", "field_type": field_type, **value},
        )
        assert tuple(
            name for name in payload if name in {"singleSelectOptionId", "text", "number", "date"}
        ) == (key,)
    with pytest.raises(InvalidControlRoom):
        _typed_input(
            "set_field_value",
            {
                "project_id": "P",
                "item_id": "I",
                "field_id": "F",
                "field_type": "number",
                "logical_value": True,
            },
        )


def test_round2_mutation_identity_has_no_legacy_fallbacks() -> None:
    with pytest.raises(InvalidControlRoom):
        _mutation_id("create_project", {"id": "P"})
    with pytest.raises(InvalidControlRoom):
        _mutation_id("create_project", {"data": {"node": {"id": "P"}}})


def test_round2_remote_values_are_frozen_typed_models() -> None:
    value = RemoteFieldValue(id="V", field_id="F", field_type="number", number=2)
    with pytest.raises(ValidationError):
        value.number = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RemoteFieldValue(id="V", field_id="F", field_type="number", number=True)


def test_plan_is_dependency_ordered_and_printable() -> None:
    state = make_control_room_state()
    plan = GitHubProvisioner(_FakeMutationTransport()).plan(
        state, RemoteGitHubState(owner="Ven-Z8", repository="Ven-Z8/agentops-harness")
    )
    resources = [action.resource for action in plan.actions]
    assert resources.index("project") < resources.index("field") < resources.index("issue")
    assert resources.index("issue") < resources.index("item") < resources.index("field-value")
    assert resources.index("field-value") < resources.index("view")
    assert json.loads(plan.to_json())["actions"]
    assert "GitHub Provisioning Plan" in plan.to_markdown()


def test_apply_requires_mutation_transport_after_pure_planning() -> None:
    state = make_control_room_state()
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        owner_id="USER_1",
        repository_id="REPO_1",
    )
    provisioner = GitHubProvisioner()

    plan = provisioner.plan(state, remote)

    with pytest.raises(InvalidControlRoom, match="apply requires a mutate-only transport"):
        provisioner.apply(plan)


def test_issue_update_preserves_unmanaged_preamble() -> None:
    state = make_control_room_state()
    item = state.roadmap.items[0]
    canonical = render_issue_body(item, state.roadmap)
    existing = "<!-- human comment -->\n\n" + "old managed content\n"
    merged = merge_managed_issue_body(existing, canonical)
    assert merged.startswith("<!-- human comment -->\n\nold managed content\n")
    assert canonical in merged


def test_new_issue_body_contains_one_managed_region() -> None:
    state = make_control_room_state()
    plan = GitHubProvisioner(_FakeMutationTransport()).plan(
        state, RemoteGitHubState(owner="Ven-Z8", repository="Ven-Z8/agentops-harness")
    )
    body = plan.issue_actions[0].payload["body"]
    assert body.count("<!-- agentops-managed:start -->") == 1
    assert body.count("<!-- agentops-managed:end -->") == 1


def test_duplicate_managed_regions_fail_closed() -> None:
    state = make_control_room_state()
    item = state.roadmap.items[0]
    body = (
        "<!-- agentops-managed:start -->x<!-- agentops-managed:end -->\n"
        "<!-- agentops-managed:start -->y<!-- agentops-managed:end -->"
    )
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        issues=[
            RemoteIssue(
                task_id=item.id,
                node_id="I_AO-D01-01",
                number=1,
                url="https://github.com/Ven-Z8/agentops-harness/issues/1",
                title=item.title,
                body=body,
            )
        ],
    )
    with pytest.raises(ValueError, match="managed"):
        GitHubProvisioner(_FakeMutationTransport()).plan(state, remote)


def test_reconciliation_report_is_strict_and_immutable() -> None:
    report = ReconciliationReport(state="success")
    with pytest.raises((TypeError, ValidationError)):
        report.state = "partial"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ReconciliationReport.model_validate({"state": "success", "unknown": True})


def test_apply_transport_wraps_operation_input_and_rejects_missing_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class Result:
        returncode = 0
        stdout = '{"data":{"createProjectV2":{"projectV2":{"id":"PVT_1"}}}}'

    monkeypatch.setattr(
        "app.project_control.github.subprocess.run",
        lambda *args, **kwargs: captured.append(json.loads(kwargs["input"])) or Result(),
    )
    with pytest.raises(Exception, match="owner"):
        ApplyGhTransport().mutate("create_project", {"title": "Wanted"})
    ApplyGhTransport().mutate("create_project", {"owner_id": "U_1", "title": "Wanted"})
    assert set(captured[0]["variables"]) == {"input"}
    assert captured[0]["variables"]["input"]["ownerId"] == "U_1"


def test_allowlist_rejects_unregistered_mutation() -> None:
    with pytest.raises(InvalidControlRoom, match="unsupported"):
        ApplyGhTransport().mutate("delete_project", {})


def test_unsupported_views_are_partial_with_six_manual_instructions() -> None:
    state = make_control_room_state()
    remote = RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        owner_id="USER_1",
        repository_id="REPO_1",
    )

    class ViewUnsupported(_FakeMutationTransport):
        def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
            if operation == "create_view":
                raise NotImplementedError
            return super().mutate(operation, variables)

    report = GitHubProvisioner(ViewUnsupported()).apply(
        GitHubProvisioner(ViewUnsupported()).plan(state, remote)
    )
    assert report.state == "partial"
    assert len(report.manual_instructions) == 6
    assert tuple(report.manual_instructions) == MANUAL_VIEW_INSTRUCTIONS


@pytest.mark.parametrize(
    "returned_options",
    (
        ("Ready", "Inbox"),
        ("Inbox", "Inbox"),
        ("Inbox",),
        ("Inbox", "Ready", "Blocked"),
    ),
    ids=("reordered", "duplicate", "missing", "extra"),
)
def test_field_mutation_option_names_must_exactly_match_the_desired_order(
    returned_options: tuple[str, ...],
) -> None:
    plan = _field_and_views_plan(with_views=False)

    class WrongOptions(_FakeMutationTransport):
        def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
            response = super().mutate(operation, variables)
            if operation == "create_field":
                response["data"]["createProjectV2Field"]["projectV2Field"]["options"] = [
                    {"id": f"OPT_{index}", "name": name}
                    for index, name in enumerate(returned_options, start=1)
                ]
            return response

    report = GitHubProvisioner(
        WrongOptions(), rediscover=lambda: _rediscovered_field_and_views_state()
    ).apply(plan)

    assert report.state == "partial"
    assert report.error is not None
    assert [action.stable_key for action in report.attempted_actions] == ["Status"]
    assert [action.stable_key for action in report.completed_actions] == ["project"]
    assert report.remaining_actions[0].stable_key == "Status"


def test_unsupported_views_are_excluded_from_post_apply_rediscovery_only() -> None:
    plan = _field_and_views_plan()

    class ViewsUnsupported(_FakeMutationTransport):
        def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
            if operation == "create_view":
                raise NotImplementedError
            return super().mutate(operation, variables)

    rediscovered = _rediscovered_field_and_views_state()
    report = GitHubProvisioner(ViewsUnsupported(), rediscover=lambda: rediscovered).apply(plan)

    assert report.state == "partial"
    assert report.error is None
    assert tuple(report.manual_instructions) == MANUAL_VIEW_INSTRUCTIONS


def test_supported_views_still_require_exact_post_apply_configuration() -> None:
    plan = _field_and_views_plan()

    class SomeViewsUnsupported(_FakeMutationTransport):
        def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
            if operation == "create_view" and variables["name"] != "Inbox":
                raise NotImplementedError
            return super().mutate(operation, variables)

    rediscovered = _rediscovered_field_and_views_state(
        views=(RemoteView(id="NODE_2", name="Inbox", layout="BOARD"),)
    )
    report = GitHubProvisioner(SomeViewsUnsupported(), rediscover=lambda: rediscovered).apply(plan)

    assert report.state == "partial"
    assert report.manual_instructions == MANUAL_VIEW_INSTRUCTIONS
    assert report.error == "post-apply view layout mismatch: Inbox"


def test_unrelated_view_failures_remain_normal_partial_errors() -> None:
    plan = _field_and_views_plan()

    class BrokenView(_FakeMutationTransport):
        def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
            if operation == "create_view":
                raise RuntimeError("injected view failure")
            return super().mutate(operation, variables)

    report = GitHubProvisioner(BrokenView()).apply(plan)

    assert report.state == "partial"
    assert report.manual_instructions == ()
    assert report.error is not None
    assert report.error.startswith("injected view failure")


def _field_and_views_plan(*, with_views: bool = True) -> ProvisioningPlan:
    return ProvisioningPlan(
        project=ProvisionAction(
            resource="project",
            stable_key="project",
            action="reuse",
            remote_id="P1",
            payload={
                "name": "Wanted",
                "owner": "Ven-Z8",
                "repository": "Ven-Z8/agentops-harness",
                "owner_id": "U1",
                "repository_id": "R1",
            },
        ),
        field_actions=(
            ProvisionAction(
                resource="field",
                stable_key="Status",
                action="create",
                remote_id=None,
                payload={
                    "name": "Status",
                    "data_type": "SINGLE_SELECT",
                    "options": ("Inbox", "Ready"),
                },
            ),
        ),
        view_actions=(
            tuple(
                ProvisionAction(
                    resource="view",
                    stable_key=name,
                    action="create",
                    remote_id=None,
                    payload={"name": name, "project": "Wanted", **VIEW_SPECS[name]},
                )
                for name in DESIRED_VIEWS
            )
            if with_views
            else ()
        ),
    )


def _rediscovered_field_and_views_state(*, views: tuple[RemoteView, ...] = ()) -> RemoteGitHubState:
    return RemoteGitHubState(
        owner="Ven-Z8",
        repository="Ven-Z8/agentops-harness",
        owner_id="U1",
        repository_id="R1",
        project=RemoteProject(
            id="P1",
            number=1,
            name="Wanted",
            url="https://github.com/users/Ven-Z8/projects/1",
        ),
        fields=(
            RemoteField(
                id="NODE_1",
                name="Status",
                data_type="SINGLE_SELECT",
                options=(
                    {"id": "OPT_1", "name": "Inbox"},
                    {"id": "OPT_2", "name": "Ready"},
                ),
            ),
        ),
        views=views,
    )


def test_discovery_rejects_ambiguous_project_names() -> None:
    from app.project_control.github import GitHubClient

    response = {
        "data": {
            "user": {
                "projectsV2": {
                    "nodes": [
                        {
                            "id": "P1",
                            "number": 1,
                            "title": "Wanted",
                            "url": "https://github.com/users/Ven-Z8/projects/1",
                        },
                        {
                            "id": "P2",
                            "number": 2,
                            "title": "Wanted",
                            "url": "https://github.com/users/Ven-Z8/projects/2",
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    with pytest.raises(InvalidControlRoom, match="ambiguous"):
        GitHubClient(_DiscoveryTransport(response)).discover_state(
            "Ven-Z8", "Ven-Z8/agentops-harness", "Wanted"
        )


class _DiscoveryTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        assert "mutation" not in query.lower()
        return self.response


class _FakeMutationTransport:
    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_after = fail_after

    def mutate(self, operation: str, variables: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, variables))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RuntimeError("injected mutation failure")
        paths = {
            "create_project": ("createProjectV2", "projectV2"),
            "update_project": ("updateProjectV2", "projectV2"),
            "create_field": ("createProjectV2Field", "projectV2Field"),
            "update_field": ("updateProjectV2Field", "projectV2Field"),
            "create_issue": ("createIssue", "issue"),
            "update_issue": ("updateIssue", "issue"),
            "add_item": ("addProjectV2ItemById", "item"),
            "set_field_value": ("updateProjectV2ItemFieldValue", "projectV2Item"),
            "create_view": ("createProjectV2View", "projectV2View"),
            "update_view": ("updateProjectV2View", "projectV2View"),
        }
        root, node = paths[operation]
        value: dict[str, object] = {"id": f"NODE_{len(self.calls)}"}
        if operation in {"create_field", "update_field"}:
            value["name"] = variables.get("name", "Field")
            value["options"] = [
                {"id": f"OPT_{index}", "name": name}
                for index, name in enumerate(variables.get("options", []), 1)
            ]
        return {"data": {root: {node: value}}}
