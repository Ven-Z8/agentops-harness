from __future__ import annotations

from pathlib import Path

from app.project_control.roadmap import load_roadmap, render_issue_body, render_roadmap

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
