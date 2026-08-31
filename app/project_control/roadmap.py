from __future__ import annotations

from pathlib import Path
from shlex import split as shell_split

from app.project_control.io import load_yaml, resolve_inside
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
    for item in roadmap.items:
        if item.verification_readiness != "available":
            continue
        for command in item.verification_commands:
            arguments = shell_split(command)
            if arguments[:3] != ["uv", "run", "pytest"]:
                continue
            for argument in arguments[3:]:
                test_path = argument.split("::", maxsplit=1)[0]
                if not test_path.startswith("tests/"):
                    continue
                resolved = resolve_inside(root / test_path, root)
                if not resolved.is_file():
                    raise ValueError(
                        f"available verification command for {item.id} references missing test: "
                        f"{test_path}"
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
        render_bullets(verification_heading(item), item.verification_commands),
        render_bullets("Risks", item.risks),
        "## Rollback\n" + item.rollback,
        render_bullets("Source documents", item.source_documents),
    ]
    return [f"## {item.id}: {item.title}", "", *metadata, "", *sections, ""]


def verification_heading(item: RoadmapItem) -> str:
    if item.verification_readiness == "planned":
        return "Planned verification commands (not current evidence)"
    return "Verification commands"


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
    canonical_item = next((record for record in roadmap.items if record.id == item.id), None)
    if canonical_item is None:
        raise ValueError(f"Roadmap does not include item: {item.id}")
    return "\n".join(
        [
            f"Task ID: {canonical_item.id}",
            "",
            "Source: `coordination/roadmap/14-day-plan.yaml`",
            "",
            "## Outcome",
            canonical_item.outcome,
            "",
            render_bullets("Scope", canonical_item.scope),
            render_bullets("Non-goals", canonical_item.non_goals),
            render_bullets("Dependencies", canonical_item.dependencies),
            render_bullets("Acceptance criteria", canonical_item.acceptance_criteria),
            render_bullets("Required evidence", canonical_item.required_evidence),
            render_bullets(
                verification_heading(canonical_item), canonical_item.verification_commands
            ),
        ]
    ).rstrip() + "\n"
