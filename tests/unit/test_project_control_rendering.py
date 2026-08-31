from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.project_control.roadmap import load_roadmap, render_issue_body, render_roadmap
from tests.helpers_project_control import valid_project_config, valid_roadmap_item

EXPECTED_IDS = {
    "AO-14D",
    "AO-P1",
    "AO-P2",
    "AO-P3",
    "AO-P4",
    "AO-P5",
    "AO-P6",
    "AO-D01",
    "AO-D01-01",
    "AO-D01-02",
    "AO-D01-03",
    "AO-D01-04",
    "AO-D02",
    "AO-D02-01",
    "AO-D02-02",
    "AO-D02-03",
    "AO-D02-04",
    "AO-D02-05",
    "AO-D03",
    "AO-D04",
    "AO-D05",
    "AO-D06",
    "AO-D07",
    "AO-D08",
    "AO-D09",
    "AO-D10",
    "AO-D11",
    "AO-D12",
    "AO-D13",
    "AO-D14",
}

VERIFICATION_MARKERS = {
    "AO-14D": "tests/unit/test_project_control_rendering.py",
    "AO-P1": "tests/test_langgraph_workflow.py",
    "AO-P2": "tests/test_benchmark.py",
    "AO-P3": "tests/test_training_contracts.py",
    "AO-P4": "tests/test_capability_pack.py",
    "AO-P5": "tests/test_vlm_reference_workflow.py",
    "AO-P6": "tests/test_release_hygiene.py",
    "AO-D01": "tests/test_langgraph_workflow.py",
    "AO-D02": "tests/test_permission_gate.py",
    "AO-D03": "tests/test_experiment_identity.py",
    "AO-D04": "tests/test_deepeval_adapter.py",
    "AO-D05": "tests/test_benchmark.py",
    "AO-D06": "tests/test_training_contracts.py",
    "AO-D07": "tests/test_governed_training.py",
    "AO-D08": "tests/test_training_promotion.py",
    "AO-D09": "tests/test_capability_pack.py",
    "AO-D10": "tests/test_strategy_pack.py",
    "AO-D11": "tests/test_vlm_reference_workflow.py",
    "AO-D12": "tests/test_vla_provider_seam.py",
    "AO-D13": "tests/test_release_hygiene.py",
    "AO-D14": "tests/test_v0_1_reproduction.py",
}


def test_committed_roadmap_has_complete_stable_inventory(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)

    assert {item.id for item in roadmap.items} == EXPECTED_IDS
    assert all(item.maturity == "confirmed" for item in roadmap.items if item.day in {1, 2})
    assert all(
        item.maturity == "needs-revalidation"
        for item in roadmap.items
        if item.day and item.day >= 3
    )


def test_roadmap_render_is_deterministic(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)

    first = render_roadmap(roadmap)
    second = render_roadmap(roadmap)

    assert first == second
    assert "Generated from `coordination/roadmap/14-day-plan.yaml`" in first
    assert "AO-D01-02" in first


def test_issue_body_renders_authoritative_fields(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    item = next(item for item in roadmap.items if item.id == "AO-D01-02")

    rendered = render_issue_body(item, roadmap)

    assert rendered.startswith("Task ID: AO-D01-02\n")
    assert "## Acceptance criteria" in rendered
    assert "Required test failure produces a non-successful run terminal state." in rendered


def test_issue_body_uses_canonical_roadmap_item(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    canonical = next(item for item in roadmap.items if item.id == "AO-D01-02")
    modified = canonical.model_copy(update={"outcome": "Unapproved caller-supplied outcome."})

    rendered = render_issue_body(modified, roadmap)

    assert canonical.outcome in rendered
    assert "Unapproved caller-supplied outcome." not in rendered


def test_parent_and_deferred_records_have_record_specific_verification_commands(
    repo_root: Path,
) -> None:
    roadmap = load_roadmap(repo_root)

    assert {item.id for item in roadmap.items if item.kind != "task"} == set(VERIFICATION_MARKERS)
    for item in roadmap.items:
        if item.kind == "task":
            continue
        assert any(
            VERIFICATION_MARKERS[item.id] in command for command in item.verification_commands
        )


def test_available_roadmap_item_rejects_missing_pytest_target(tmp_path: Path) -> None:
    project = valid_project_config()
    item = valid_roadmap_item("AO-D01-01")
    item["verification_readiness"] = "available"
    item["verification_commands"] = ["uv run pytest tests/test_missing_target.py -q"]
    (tmp_path / "coordination/roadmap").mkdir(parents=True)
    (tmp_path / "coordination/project.yaml").write_text(yaml.safe_dump(project), encoding="utf-8")
    (tmp_path / "coordination/roadmap/14-day-plan.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="available.*test_missing_target.py"):
        load_roadmap(tmp_path)


def test_planned_roadmap_item_allows_missing_pytest_target(tmp_path: Path) -> None:
    project = valid_project_config()
    item = valid_roadmap_item("AO-D01-01")
    item["verification_readiness"] = "planned"
    item["verification_commands"] = ["uv run pytest tests/test_missing_target.py -q"]
    (tmp_path / "coordination/roadmap").mkdir(parents=True)
    (tmp_path / "coordination/project.yaml").write_text(yaml.safe_dump(project), encoding="utf-8")
    (tmp_path / "coordination/roadmap/14-day-plan.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]}),
        encoding="utf-8",
    )

    assert load_roadmap(tmp_path).items[0].verification_readiness == "planned"


def test_needs_revalidation_records_are_planned(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)

    assert all(
        item.verification_readiness == "planned"
        for item in roadmap.items
        if item.maturity == "needs-revalidation"
    )


def test_rendering_labels_planned_verification_as_not_current_evidence(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    planned_item = next(item for item in roadmap.items if item.id == "AO-D03")

    assert "## Planned verification commands (not current evidence)" in render_roadmap(roadmap)
    assert "## Planned verification commands (not current evidence)" in render_issue_body(
        planned_item, roadmap
    )


def test_available_top_level_roadmap_targets_exist(repo_root: Path) -> None:
    roadmap = load_roadmap(repo_root)
    item = next(item for item in roadmap.items if item.id == "AO-14D")

    assert item.verification_readiness == "available"
    for command in item.verification_commands:
        if not command.startswith("uv run pytest"):
            continue
        for target in command.split()[3:]:
            if target.startswith("tests/"):
                assert (repo_root / target.split("::", maxsplit=1)[0]).is_file()
