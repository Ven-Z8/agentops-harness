from __future__ import annotations

from pathlib import Path

from app.project_control.io import load_yaml
from app.project_control.models import ProjectConfig, Roadmap, RoadmapItem


def load_roadmap(root: Path) -> Roadmap:
    """Load the roadmap from the versioned project configuration."""
    project = load_yaml(root / "coordination/project.yaml", ProjectConfig, root=root)
    roadmap = load_yaml(root / project.roadmap.source, Roadmap, root=root)
    if roadmap.roadmap_id != project.roadmap.id:
        raise ValueError(
            "Roadmap ID does not match project configuration: "
            f"{roadmap.roadmap_id!r} != {project.roadmap.id!r}"
        )
    return roadmap


def roadmap_sort_key(item: RoadmapItem) -> tuple[int, int, str]:
    kind_order = {"roadmap": 0, "phase": 1, "outcome": 2, "task": 3}
    return (item.day or 0, kind_order[item.kind], item.id)


def render_bullets(heading: str, values: list[str]) -> str:
    lines = [f"## {heading}"]
    lines.extend(f"- {value}" for value in values or ["None"])
    return "\n".join(lines)


def render_item(item: RoadmapItem) -> list[str]:
    metadata = [
        f"- Kind: {item.kind}",
        f"- Day: {item.day if item.day is not None else 'None'}",
        f"- Phase: {item.phase_id or 'None'}",
        f"- Parent: {item.parent_id or 'None'}",
        f"- Status: {item.status}",
        f"- Maturity: {item.maturity}",
        f"- Priority: {item.priority}",
        f"- Risk: {item.risk}",
        f"- Blocker: {item.blocker}",
    ]
    sections = [
        "## Outcome\n" + item.outcome,
        render_bullets("Scope", item.scope),
        render_bullets("Non-goals", item.non_goals),
        render_bullets("Dependencies", item.dependencies),
        render_bullets("Acceptance criteria", item.acceptance_criteria),
        render_bullets("Required evidence", item.required_evidence),
        render_bullets("Likely files", item.likely_files),
        "## First failing test\n" + (item.test_first or "None"),
        "## Terminal semantics\n" + item.terminal_semantics,
        "## Compatibility\n" + item.compatibility,
        render_bullets("Verification commands", item.verification_commands),
        render_bullets("Risks", item.risks),
        "## Rollback\n" + item.rollback,
        render_bullets("Source documents", item.source_documents),
    ]
    return [f"## {item.id}: {item.title}", "", *metadata, "", *sections, ""]


def render_roadmap(roadmap: Roadmap) -> str:
    lines = [
        "# AgentOps 14-Day Roadmap",
        "",
        "> Generated from `coordination/roadmap/14-day-plan.yaml`; do not edit manually.",
        "",
    ]
    for item in sorted(roadmap.items, key=roadmap_sort_key):
        lines.extend(render_item(item))
    return "\n".join(lines).rstrip() + "\n"


def render_issue_body(item: RoadmapItem, roadmap: Roadmap) -> str:
    if item.id not in {record.id for record in roadmap.items}:
        raise ValueError(f"Roadmap does not include item: {item.id}")
    return "\n".join(
        [
            f"Task ID: {item.id}",
            "",
            "Source: `coordination/roadmap/14-day-plan.yaml`",
            "",
            "## Outcome",
            item.outcome,
            "",
            render_bullets("Scope", item.scope),
            render_bullets("Non-goals", item.non_goals),
            render_bullets("Dependencies", item.dependencies),
            render_bullets("Acceptance criteria", item.acceptance_criteria),
            render_bullets("Required evidence", item.required_evidence),
            render_bullets("Verification commands", item.verification_commands),
        ]
    ).rstrip() + "\n"
