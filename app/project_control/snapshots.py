"""Deterministic, validated local snapshots for the Project Control Room."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.project_control.artifacts import load_artifact_index
from app.project_control.codegraph import validate_codegraph_freshness
from app.project_control.handoffs import _expected_handoff_name
from app.project_control.io import atomic_write, load_frontmatter, load_yaml, resolve_inside
from app.project_control.models import (
    BoardExport,
    BoardItem,
    ControlRoomState,
    GraphManifest,
    HandoffHeader,
    ProjectConfig,
    RoadmapItem,
)
from app.project_control.roadmap import load_roadmap

STATUS_ORDER = {"blocked": 0, "in-progress": 1, "ready": 2, "planned": 3, "done": 4}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_HANDOFF_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def board_sort_key(item: BoardItem) -> tuple[int, int, int, str]:
    """Order exported work by live execution urgency, then stable identity."""
    return (
        STATUS_ORDER[item.status],
        PRIORITY_ORDER[item.priority],
        item.day or 0,
        item.task_id,
    )


def _roadmap_board_sort_key(item: RoadmapItem) -> tuple[int, int, int, str]:
    return (
        STATUS_ORDER[item.status],
        PRIORITY_ORDER[item.priority],
        item.day or 0,
        item.id,
    )


def _link(value: str | None, label: str) -> str:
    return f"[{label}]({value})" if value else "None"


def _phase_summaries(items: list[BoardItem]) -> list[str]:
    phases: dict[str, list[BoardItem]] = {}
    for item in items:
        phases.setdefault(item.phase_id or "Unassigned", []).append(item)
    if not phases:
        return ["- None"]
    lines: list[str] = []
    for phase_id in sorted(phases):
        phase_items = phases[phase_id]
        states = ", ".join(
            f"{status}: {sum(item.status == status for item in phase_items)}"
            for status in STATUS_ORDER
            if any(item.status == status for item in phase_items)
        )
        lines.append(f"- {phase_id}: {states}")
    return lines


def render_board(export: BoardExport, now: datetime) -> str:
    """Render a read-only, deterministic snapshot of a validated live export."""
    timestamp = _timestamp(now)
    items = sorted(export.items, key=board_sort_key)
    lines = [
        "# AgentOps Project Board",
        "",
        "> Generated snapshot; do not edit manually.",
        "> GitHub Issues and Projects are authoritative for live execution state.",
        "",
        f"- Generated at: {timestamp}",
        f"- GitHub project: {_link(export.project_url, export.project_url)}",
        f"- Source revision: `{export.source_revision or 'not supplied'}`",
        "",
        "## Phase summaries",
        "",
        *_phase_summaries(items),
        "",
        "## Blocked work",
        "",
    ]
    blocked = [item for item in items if item.status == "blocked"]
    lines.extend(
        f"- {item.task_id}: {item.title}"
        + (f" — dependency: {item.dependency}" if item.dependency else "")
        for item in blocked
    )
    if not blocked:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Live work",
            "",
            "| Task | Status | Priority | Day | Harness | Issue | Handoff | Evidence |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in items:
        issue = _link(item.issue_url, f"#{item.issue_number}") if item.issue_url else "None"
        handoff = _link(item.handoff, "handoff")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{item.task_id}: {item.title}",
                    str(item.status),
                    item.priority,
                    str(item.day) if item.day is not None else "—",
                    item.harness or "Unassigned",
                    issue,
                    handoff,
                    str(item.evidence),
                ]
            )
            + " |"
        )
    if not items:
        lines.append("| None | — | — | — | — | — | — | — |")
    lines.extend(["", "## Harness assignments", ""])
    assignments: dict[str, list[str]] = {}
    for item in items:
        assignments.setdefault(item.harness or "Unassigned", []).append(item.task_id)
    if assignments:
        lines.extend(
            f"- {harness}: {', '.join(sorted(task_ids))}"
            for harness, task_ids in sorted(assignments.items())
        )
    else:
        lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def _current_phase(state: ControlRoomState) -> RoadmapItem | None:
    phases = [
        item for item in state.roadmap.items if item.kind == "phase" and item.status != "done"
    ]
    return min(phases, key=_roadmap_board_sort_key, default=None)


def _immediate_objective(state: ControlRoomState, phase: RoadmapItem | None) -> RoadmapItem | None:
    candidates = [
        item
        for item in state.roadmap.items
        if item.status != "done" and item.kind in {"outcome", "task"}
    ]
    if phase:
        phase_candidates = [item for item in candidates if item.phase_id == phase.id]
        if phase_candidates:
            candidates = phase_candidates
    return min(candidates, key=_roadmap_board_sort_key, default=None)


def _codegraph_status(state: ControlRoomState) -> str:
    if state.graph_manifest is None:
        return "Inconclusive: no validated code-graph manifest is available."
    return (
        "Inconclusive: manifest provenance is available, but freshness must be validated "
        "against the current source tree before relying on it."
    )


def render_current(state: ControlRoomState, now: datetime) -> str:
    """Render the repository-derived entry point without inferring missing evidence."""
    timestamp = _timestamp(now)
    phase = _current_phase(state)
    objective = _immediate_objective(state, phase)
    baseline = state.graph_manifest.source_commit if state.graph_manifest else "inconclusive"
    blockers = sorted(
        (item for item in state.roadmap.items if item.status != "done" and item.blocker != "none"),
        key=_roadmap_board_sort_key,
    )
    lines = [
        "# Current Project State",
        "",
        "> Generated from validated repository state; do not edit manually.",
        "",
        f"- Generated at: {timestamp}",
        "",
        "## Current phase",
        "",
        f"- {phase.id}: {phase.title}" if phase else "- Inconclusive: no active phase is recorded.",
        "",
        "## Immediate objective",
        "",
        f"- {objective.id}: {objective.outcome}"
        if objective
        else "- Inconclusive: no active outcome or task is recorded.",
        "",
        "## Confirmed baseline",
        "",
        (
            f"- Baseline commit: `{baseline}`"
            if baseline != "inconclusive"
            else "- Baseline commit: inconclusive; no code-graph source revision is available."
        ),
        "",
        "## Active blockers",
        "",
    ]
    lines.extend(f"- {item.id}: {item.blocker}" for item in blockers)
    if not blockers:
        lines.append("- None recorded.")
    lines.extend(["", "## Latest decisions and handoffs", ""])
    if state.decisions:
        for decision_id, decision in sorted(state.decisions.items()):
            lines.append(
                f"- Decision {decision_id}: {decision.status} "
                f"({decision.date.astimezone(UTC).date()})"
            )
    if state.handoffs:
        for task_id, handoff in sorted(
            state.handoffs.items(),
            key=lambda record: (record[1].updated_at, record[0]),
            reverse=True,
        ):
            lines.append(
                f"- Handoff {task_id}: {handoff.status} at {_timestamp(handoff.updated_at)}"
            )
    if not state.decisions and not state.handoffs:
        lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Code graph freshness",
            "",
            f"- {_codegraph_status(state)}",
            "",
            "## Onboarding commands",
            "",
            "```bash",
            "git status --short",
            "uv run python scripts/project_control.py validate",
            "uv run python scripts/project_control.py snapshot",
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _latest_handoffs(root: Path) -> dict[str, HandoffHeader]:
    directory = root / "coordination" / "handoffs"
    if not directory.exists():
        return {}
    resolve_inside(directory, root)
    latest: dict[str, tuple[datetime, str, HandoffHeader]] = {}
    for path in sorted(directory.glob("*.md")):
        if not _HANDOFF_NAME.fullmatch(path.name):
            continue
        header = load_frontmatter(path, HandoffHeader, root=root)
        if _expected_handoff_name(header) != path.name:
            raise ValueError(f"Handoff filename does not match header: {path.name}")
        candidate = (header.updated_at, path.name, header)
        previous = latest.get(header.task_id)
        if previous is None or candidate[:2] > previous[:2]:
            latest[header.task_id] = candidate
    return {task_id: record[2] for task_id, record in latest.items()}


def _load_state(root: Path, board_export: BoardExport | None) -> ControlRoomState:
    root = root.resolve(strict=True)
    project = load_yaml(root / "coordination" / "project.yaml", ProjectConfig, root=root)
    roadmap = load_roadmap(root)
    artifacts = load_artifact_index(root)
    manifest_path = root / project.generated.codegraph / "manifest.json"
    manifest = None
    if manifest_path.exists():
        resolved_manifest = resolve_inside(manifest_path, root)
        manifest = GraphManifest.model_validate_json(resolved_manifest.read_text(encoding="utf-8"))
    return ControlRoomState(
        project=project,
        roadmap=roadmap,
        artifacts=artifacts,
        graph_manifest=manifest,
        board_export=board_export,
        handoffs=_latest_handoffs(root),
    )


def _codegraph_freshness(root: Path, state: ControlRoomState) -> str:
    if state.graph_manifest is None:
        return "Inconclusive: no validated code-graph manifest is available."
    try:
        validate_codegraph_freshness(root)
    except ValueError as error:
        if "Codegraph is stale" not in str(error):
            raise
        return "Stale: the source-tree digest differs from the manifest."
    return "Fresh: the manifest source-tree digest matches tracked inputs."


def _render_current_with_freshness(state: ControlRoomState, now: datetime, freshness: str) -> str:
    rendered = render_current(state, now)
    return rendered.replace(_codegraph_status(state), freshness)


def _initial_board(state: ControlRoomState, now: datetime) -> str:
    timestamp = _timestamp(now)
    items = sorted(state.roadmap.items, key=_roadmap_board_sort_key)
    lines = [
        "# AgentOps Project Board",
        "",
        "> Generated snapshot; do not edit manually.",
        "> GitHub Issues and Projects are authoritative for live execution state when provisioned.",
        "",
        f"- Generated at: {timestamp}",
        "- GitHub project: not provisioned",
        (
            "- Source revision: "
            f"`{state.graph_manifest.source_commit if state.graph_manifest else 'inconclusive'}`"
        ),
        "",
        "## Repository roadmap work",
        "",
        "| Task | Phase | Repository status | Priority | Day | Issue | Handoff |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        handoff = state.handoffs.get(item.id)
        lines.append(
            f"| {item.id}: {item.title} | {item.phase_id or '—'} | {item.status} | "
            f"{item.priority} | {item.day if item.day is not None else '—'} | not provisioned | "
            f"{'recorded' if handoff else 'None'} |"
        )
    lines.extend(["", "## Phase summaries", ""])
    phase_items = [item for item in items if item.kind == "phase"]
    lines.extend(f"- {item.id}: {item.status} — {item.title}" for item in phase_items)
    if not phase_items:
        lines.append("- None recorded.")
    lines.extend(["", "## Blocked work", ""])
    blocked = [item for item in items if item.status == "blocked"]
    lines.extend(f"- {item.id}: {item.blocker}" for item in blocked)
    if not blocked:
        lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Harness assignments",
            "",
            "- Unassigned: repository-only snapshot; live assignments require a GitHub export.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_snapshots(root: Path, board_export: BoardExport | dict, now: datetime) -> None:
    """Validate every input and render both snapshots before replacing either file."""
    _timestamp(now)
    export = BoardExport.model_validate(board_export)
    state = _load_state(root, export)
    current = _render_current_with_freshness(state, now, _codegraph_freshness(root, state))
    board = render_board(export, now)
    atomic_write(root / state.project.generated.current, current, root=root)
    atomic_write(root / state.project.generated.board, board, root=root)


def write_initial_snapshots(root: Path, now: datetime) -> None:
    """Write repository-only snapshots before a GitHub Project has been provisioned."""
    _timestamp(now)
    state = _load_state(root, None)
    current = _render_current_with_freshness(state, now, _codegraph_freshness(root, state))
    board = _initial_board(state, now)
    atomic_write(root / state.project.generated.current, current, root=root)
    atomic_write(root / state.project.generated.board, board, root=root)
