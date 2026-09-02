from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.project_control.errors import DependencyUnavailable, InvalidControlRoom
from app.project_control.github import (
    DESIRED_FIELDS,
    DESIRED_VIEWS,
    MANUAL_VIEW_INSTRUCTIONS,
    VIEW_SPECS,
    ApplyGhTransport,
    GitHubProvisioner,
    _mutation_id,
    _mutation_option_ids,
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
    assert all(
        DESIRED_FIELDS[name] == ()
        for name in ("Harness", "Dependency", "Handoff", "Target date")
    )
    assert DESIRED_VIEWS == ("Inbox", "Kanban", "Phase", "Harness", "Trust Blockers", "Roadmap")


def test_harness_definition_is_optionless_but_item_values_remain_unassigned_text() -> None:
    state = make_control_room_state()
    plan = GitHubProvisioner().plan(
        state,
        RemoteGitHubState(owner="Ven-Z8", repository="Ven-Z8/agentops-harness"),
    )

    definition = next(action for action in plan.field_actions if action.stable_key == "Harness")
    values = [
        action
        for action in plan.field_value_actions
        if action.payload.get("field") == "Harness"
    ]

    assert definition.payload["options"] == ()
    assert len(values) == len(state.roadmap.items)
    assert all(
        action.payload["field_type"] == "text"
        and action.payload["logical_value"] == "Unassigned"
        for action in values
    )


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


def test_create_day_field_input_serializes_literal_option_objects() -> None:
    payload = _typed_input(
        "create_field",
        {
            "project_id": "PVT_1",
            "name": "Day",
            "data_type": "SINGLE_SELECT",
            "options": DESIRED_FIELDS["Day"],
            "option_ids": {},
        },
    )

    assert payload == {
        "projectId": "PVT_1",
        "name": "Day",
        "dataType": "SINGLE_SELECT",
        "singleSelectOptions": [
            {"name": "Day 1", "color": "GRAY", "description": ""},
            {"name": "Day 2", "color": "GRAY", "description": ""},
            {"name": "Day 3", "color": "GRAY", "description": ""},
            {"name": "Day 4", "color": "GRAY", "description": ""},
            {"name": "Day 5", "color": "GRAY", "description": ""},
            {"name": "Day 6", "color": "GRAY", "description": ""},
            {"name": "Day 7", "color": "GRAY", "description": ""},
            {"name": "Day 8", "color": "GRAY", "description": ""},
            {"name": "Day 9", "color": "GRAY", "description": ""},
            {"name": "Day 10", "color": "GRAY", "description": ""},
            {"name": "Day 11", "color": "GRAY", "description": ""},
            {"name": "Day 12", "color": "GRAY", "description": ""},
            {"name": "Day 13", "color": "GRAY", "description": ""},
            {"name": "Day 14", "color": "GRAY", "description": ""},
        ],
    }


def test_update_status_field_input_reuses_matching_ids_without_create_only_keys() -> None:
    payload = _typed_input(
        "update_field",
        {
            "field_id": "PVTSSF_STATUS",
            "project_id": "PVT_CREATE_ONLY",
            "name": "Status",
            "data_type": "SINGLE_SELECT",
            "options": DESIRED_FIELDS["Status"],
            "option_ids": {
                "Todo": "OPT_REMOVED_TODO",
                "In progress": "OPT_IN_PROGRESS",
                "Done": "OPT_DONE",
            },
        },
    )

    assert payload == {
        "fieldId": "PVTSSF_STATUS",
        "name": "Status",
        "singleSelectOptions": [
            {"name": "Inbox", "color": "GRAY", "description": ""},
            {"name": "Ready", "color": "GRAY", "description": ""},
            {
                "name": "In progress",
                "color": "GRAY",
                "description": "",
                "id": "OPT_IN_PROGRESS",
            },
            {"name": "In review", "color": "GRAY", "description": ""},
            {"name": "Blocked", "color": "GRAY", "description": ""},
            {
                "name": "Done",
                "color": "GRAY",
                "description": "",
                "id": "OPT_DONE",
            },
        ],
    }


@pytest.mark.parametrize(
    "option_ids",
    (
        [],
        {1: "OPT_DONE"},
        {"": "OPT_DONE"},
        {"Done": ""},
        {"Done": "unsafe option id"},
        {"Inbox": "OPT_DUP", "Done": "OPT_DUP"},
    ),
    ids=(
        "not-a-map",
        "non-string-name",
        "empty-name",
        "empty-id",
        "unsafe-id",
        "duplicate-id",
    ),
)
def test_update_field_input_rejects_malformed_option_id_maps(option_ids: object) -> None:
    with pytest.raises(InvalidControlRoom, match="field option"):
        _typed_input(
            "update_field",
            {
                "field_id": "PVTSSF_STATUS",
                "name": "Status",
                "options": ("Inbox", "Done"),
                "option_ids": option_ids,
            },
        )


def test_update_field_input_rejects_duplicate_desired_option_names() -> None:
    with pytest.raises(InvalidControlRoom, match="field options"):
        _typed_input(
            "update_field",
            {
                "field_id": "PVTSSF_STATUS",
                "name": "Status",
                "options": ("Done", "Done"),
                "option_ids": {"Done": "OPT_DONE"},
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


@pytest.mark.parametrize(
    ("operation", "root", "variables"),
    (
        (
            "create_field",
            "createProjectV2Field",
            {
                "project_id": "PVT_1",
                "name": "Day",
                "data_type": "SINGLE_SELECT",
                "options": ["Day 1"],
            },
        ),
        (
            "update_field",
            "updateProjectV2Field",
            {
                "project_id": "PVT_1",
                "field_id": "PVTF_1",
                "name": "Day",
                "data_type": "SINGLE_SELECT",
                "options": ["Day 1"],
            },
        ),
    ),
)
def test_field_mutation_documents_select_union_variants(
    operation: str,
    root: str,
    variables: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    response = {
        "data": {
            root: {
                "projectV2Field": {
                    "__typename": "ProjectV2SingleSelectField",
                    "id": "PVTF_1",
                    "name": "Day",
                    "dataType": "SINGLE_SELECT",
                    "options": [{"id": "OPT_1", "name": "Day 1"}],
                }
            }
        }
    }

    class Result:
        returncode = 0
        stdout = json.dumps(response)

    monkeypatch.setattr(
        "app.project_control.github.subprocess.run",
        lambda *args, **kwargs: captured.append(json.loads(kwargs["input"])) or Result(),
    )

    assert ApplyGhTransport().mutate(operation, variables) == response

    query = " ".join(captured[0]["query"].split())
    assert "projectV2Field { __typename" in query
    assert "... on ProjectV2Field { id name dataType }" in query
    assert (
        "... on ProjectV2SingleSelectField { id name dataType options { id name } }" in query
    )
    assert "... on ProjectV2IterationField { id name dataType }" in query
    assert "... on ProjectV2MultiSelectField { id name dataType }" in query
    assert "projectV2Field { id name dataType options" not in query


@pytest.mark.parametrize(
    ("operation", "root"),
    (
        ("create_field", "createProjectV2Field"),
        ("update_field", "updateProjectV2Field"),
    ),
)
@pytest.mark.parametrize(
    "typename",
    ("ProjectV2Field", "ProjectV2IterationField", "ProjectV2MultiSelectField"),
)
def test_field_mutation_options_allow_omission_for_exact_non_select_variants(
    operation: str,
    root: str,
    typename: str,
) -> None:
    response = {
        "data": {
            root: {
                "projectV2Field": {
                    "__typename": typename,
                    "id": "PVTF_1",
                    "name": "Field",
                    "dataType": "TEXT",
                }
            }
        }
    }

    assert _mutation_option_ids(operation, response) == {}


def test_field_mutation_options_require_options_for_single_select() -> None:
    response = {
        "data": {
            "createProjectV2Field": {
                "projectV2Field": {
                    "__typename": "ProjectV2SingleSelectField",
                    "id": "PVTF_1",
                    "name": "Day",
                    "dataType": "SINGLE_SELECT",
                }
            }
        }
    }

    with pytest.raises(InvalidControlRoom, match="options"):
        _mutation_option_ids("create_field", response)


@pytest.mark.parametrize(
    "field",
    (
        {
            "__typename": "ProjectV2RepositoryField",
            "id": "PVTF_1",
            "name": "Repository",
            "dataType": "REPOSITORY",
            "options": [],
        },
        {
            "__typename": "ProjectV2Field",
            "id": "PVTF_1",
            "name": "Harness",
            "dataType": "TEXT",
            "options": [],
        },
    ),
)
def test_field_mutation_options_reject_unknown_or_impossible_variant_shape(
    field: dict[str, object],
) -> None:
    response = {
        "data": {"createProjectV2Field": {"projectV2Field": field}},
    }

    with pytest.raises(InvalidControlRoom, match="type|options"):
        _mutation_option_ids("create_field", response)


@pytest.mark.parametrize(
    ("stdout", "stderr", "required_context", "credential_values"),
    (
        (
            json.dumps(
                {
                    "errors": [
                        {
                            "message": (
                                "Selections can't be made directly on unions "
                                "(token=TOP_SECRET)"
                            )
                        }
                    ]
                }
            ),
            "",
            ("Selections can't be made directly on unions",),
            ("TOP_SECRET",),
        ),
        (
            "",
            "gh: GraphQL: Selections can't be made directly on unions "
            "(token=TOP_SECRET)",
            ("Selections can't be made directly on unions",),
            ("TOP_SECRET",),
        ),
        (
            "",
            "gh: GraphQL: Cannot query field options\n"
            "AuThOrIzAtIoN: bEaReR ghp_AUTH_VALUE",
            ("Cannot query field options",),
            ("ghp_AUTH_VALUE",),
        ),
        (
            "",
            "gh: GraphQL: Unknown field options TOKEN=TOKEN_VALUE "
            "Secret: SECRET_VALUE PASSWORD = PASSWORD_VALUE",
            ("Unknown field options",),
            ("TOKEN_VALUE", "SECRET_VALUE", "PASSWORD_VALUE"),
        ),
        (
            "",
            "gh: GraphQL: authorization policy rejected requested field\n"
            "Authorization: Bearer ghp_MULTILINE_AUTH\n"
            "X-GitHub-Token: gho_MULTILINE_TOKEN\n"
            "secret=SECRET_MULTILINE\n"
            "password: PASSWORD_MULTILINE\n"
            "Cannot query field options",
            (
                "authorization policy rejected requested field",
                "Cannot query field options",
            ),
            (
                "ghp_MULTILINE_AUTH",
                "gho_MULTILINE_TOKEN",
                "SECRET_MULTILINE",
                "PASSWORD_MULTILINE",
            ),
        ),
    ),
    ids=(
        "structured-stdout",
        "graphql-stderr",
        "authorization-bearer-case-insensitive",
        "token-secret-password-forms",
        "multiline-header-shaped-content",
    ),
)
def test_apply_transport_preserves_sanitized_graphql_validation_evidence(
    stdout: str,
    stderr: str,
    required_context: tuple[str, ...],
    credential_values: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        returncode = 1

    Result.stdout = stdout
    Result.stderr = stderr

    monkeypatch.setattr("app.project_control.github.subprocess.run", lambda *_a, **_k: Result())

    with pytest.raises(InvalidControlRoom) as raised:
        ApplyGhTransport().mutate(
            "create_field",
            {
                "project_id": "PVT_1",
                "name": "Day",
                "data_type": "SINGLE_SELECT",
                "options": ["Day 1"],
            },
        )

    assert not isinstance(raised.value, DependencyUnavailable)
    message = str(raised.value)
    prefix = "GitHub mutation GraphQL request failed: "
    assert message.startswith(prefix)
    assert all(context in message for context in required_context)
    assert all(value not in message for value in credential_values)
    assert len(message) <= len(prefix) + 500


def test_apply_transport_bounds_sanitized_graphql_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = (
            "gh: GraphQL: Cannot query field options "
            + ("ordinary-context " * 80)
            + "\nAuthorization: Bearer ghp_AFTER_LONG_CONTEXT"
        )

    monkeypatch.setattr("app.project_control.github.subprocess.run", lambda *_a, **_k: Result())

    with pytest.raises(InvalidControlRoom) as raised:
        ApplyGhTransport().mutate(
            "create_field",
            {
                "project_id": "PVT_1",
                "name": "Day",
                "data_type": "SINGLE_SELECT",
                "options": ["Day 1"],
            },
        )

    message = str(raised.value)
    prefix = "GitHub mutation GraphQL request failed: "
    assert message.startswith(prefix)
    assert "Cannot query field options" in message
    assert "ghp_AFTER_LONG_CONTEXT" not in message
    assert len(message) <= len(prefix) + 500


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
            value["__typename"] = (
                "ProjectV2SingleSelectField"
                if variables.get("data_type") == "SINGLE_SELECT"
                else "ProjectV2Field"
            )
            value["dataType"] = variables.get("data_type", "TEXT")
            value["name"] = variables.get("name", "Field")
            if value["__typename"] == "ProjectV2SingleSelectField":
                value["options"] = [
                    {"id": f"OPT_{index}", "name": name}
                    for index, name in enumerate(variables.get("options", []), 1)
                ]
        return {"data": {root: {node: value}}}
