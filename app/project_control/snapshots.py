"""Deterministic, validated local snapshots for the Project Control Room."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.project_control.artifacts import load_artifact_index
from app.project_control.codegraph import tracked_graph_inputs, validate_codegraph_freshness
from app.project_control.decisions import load_recent_decisions
from app.project_control.handoffs import load_latest_handoffs
from app.project_control.io import load_yaml, resolve_inside
from app.project_control.models import (
    BoardExport,
    BoardItem,
    ControlRoomState,
    GraphManifest,
    ProjectConfig,
    RoadmapItem,
    _https_url,
    _safe_relative_link_target,
)
from app.project_control.roadmap import load_roadmap

STATUS_ORDER = {"blocked": 0, "in-progress": 1, "ready": 2, "planned": 3, "done": 4}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


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


def _local_link(value: str | None, label: str) -> str:
    if not value:
        return "None"
    if value.startswith("https://"):
        return f"[{_markdown(label)}](<{_https_url(value)}>)"
    return f"[{_markdown(label)}](<{_safe_relative_link_target(value)}>)"


def _url_link(value: str | None, label: str) -> str:
    if not value:
        return "None"
    return f"[{_markdown(label)}](<{_https_url(value)}>)"


def _markdown(value: str) -> str:
    single_line = "".join(
        " " if ord(character) < 32 or ord(character) == 127 else character for character in value
    )
    value = " ".join(single_line.split())
    for character in "\\|[]()<>#*_`":
        value = value.replace(character, f"\\{character}")
    return value


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
        lines.append(f"- {_markdown(phase_id)}: {states}")
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
        f"- GitHub project: {_url_link(export.project_url, export.project_url)}",
        f"- Snapshot input revision: `{export.source_revision}`",
        "- Generated snapshot outputs are excluded from this revision.",
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
        f"- {_markdown(item.task_id)}: {_markdown(item.title)}"
        + (f" — dependency: {_markdown(item.dependency)}" if item.dependency else "")
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
        issue = _url_link(item.issue_url, f"#{item.issue_number}") if item.issue_url else "None"
        handoff = _local_link(item.handoff, "handoff")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{_markdown(item.task_id)}: {_markdown(item.title)}",
                    _markdown(str(item.status)),
                    item.priority,
                    str(item.day) if item.day is not None else "—",
                    _markdown(item.harness or "Unassigned"),
                    issue,
                    handoff,
                    _markdown(str(item.evidence)),
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
            f"- {_markdown(harness)}: "
            f"{', '.join(_markdown(task_id) for task_id in sorted(task_ids))}"
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
        return "Graph provenance unavailable; freshness inconclusive."
    return (
        f"Graph input provenance: `{state.graph_manifest.source_commit}`; freshness is "
        "inconclusive until validated "
        "against the current source tree before relying on it."
    )


def render_current(state: ControlRoomState, now: datetime) -> str:
    """Render the repository-derived entry point without inferring missing evidence."""
    timestamp = _timestamp(now)
    phase = _current_phase(state)
    objective = _immediate_objective(state, phase)
    live = sorted(state.board_export.items, key=board_sort_key) if state.board_export else []
    if state.board_export is not None:
        active = [item for item in live if item.status != "done"]
        phase_id = next((item.phase_id for item in active if item.phase_id), "Unassigned")
        phase_text = f"- {_markdown(phase_id)} (live board)"
        objective_text = (
            f"- {_markdown(active[0].task_id)}: {_markdown(active[0].title)}"
            if active
            else "- None"
        )
        blockers = [item for item in active if item.status == "blocked"]
    else:
        phase_text = (
            f"- {_markdown(phase.id)}: {_markdown(phase.title)} (roadmap fallback)"
            if phase
            else "- Inconclusive."
        )
        objective_text = (
            f"- {_markdown(objective.id)}: {_markdown(objective.outcome)} (roadmap fallback)"
            if objective
            else "- Inconclusive."
        )
        blockers = sorted(
            (
                item
                for item in state.roadmap.items
                if item.status != "done" and item.blocker != "none"
            ),
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
        phase_text,
        "",
        "## Immediate objective",
        "",
        objective_text,
        "",
        "## Confirmed baseline",
        "",
        f"- Baseline commit: `{state.approved_baseline}`",
        f"- Snapshot input revision: `{state.snapshot_source_revision}`",
        "- Generated snapshot outputs are excluded; unavailable means validated "
        "inputs are dirty or provenance could not be resolved.",
        "",
        "## Active blockers",
        "",
    ]
    lines.extend(
        f"- {_markdown(item.task_id)}: "
        f"{_markdown(item.blocker or item.dependency or 'not specified')}"
        if isinstance(item, BoardItem)
        else f"- {_markdown(item.id)}: {_markdown(item.blocker)}"
        for item in blockers
    )
    if not blockers:
        lines.append("- None recorded.")
    lines.extend(["", "## Latest decisions and handoffs", ""])
    if state.decisions:
        decisions = sorted(
            state.decisions.items(),
            key=lambda item: (item[1].date, item[0]),
            reverse=True,
        )
        for decision_id, decision in decisions:
            label = f"Decision {decision_id}"
            lines.append(
                f"- {_local_link(state.decision_paths.get(decision_id), label)}: {decision.status}"
            )
    if state.handoffs:
        for task_id, handoff in sorted(
            state.handoffs.items(),
            key=lambda record: (record[1].updated_at, record[0]),
            reverse=True,
        ):
            lines.append(
                f"- {_local_link(state.handoff_paths.get(task_id), f'Handoff {task_id}')}: "
                f"{handoff.status}"
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


def _snapshot_source_revision(root: Path) -> str:
    """Return a clean revision for the resolved snapshot inputs, or ``unavailable``.

    Generated CURRENT/BOARD files and ignored orchestration reports are excluded
    so an output-only commit cannot invalidate its own fixed-clock snapshots.
    """
    try:
        root = root.resolve(strict=True)
        project_path = resolve_inside(root / "coordination" / "project.yaml", root)
        project = load_yaml(project_path, ProjectConfig, root=root)
        inputs = _snapshot_input_paths(root, project, project_path)
        if _inputs_are_dirty(root, inputs):
            return "unavailable"
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", *sorted(inputs)],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return "unavailable"
    revision = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", revision):
        return revision
    return "unavailable"


def _snapshot_input_paths(root: Path, project: ProjectConfig, project_path: Path) -> set[str]:
    """Resolve every validated file that loading, rendering, or freshness consumes."""
    control_root = project_path.relative_to(root).parent
    manifest_path = Path(project.generated.codegraph) / "manifest.json"
    paths = {
        project_path.relative_to(root).as_posix(),
        Path(project.roadmap.source).as_posix(),
        (control_root / "artifacts" / "index.yaml").as_posix(),
        manifest_path.as_posix(),
    }
    for directory_name in ("handoffs", "decisions"):
        directory = control_root / directory_name
        paths.update(_record_input_paths(root, directory))
    for path in tracked_graph_inputs(root, config=project):
        relative = path.as_posix()
        if not _excluded_snapshot_output(relative, project):
            paths.add(relative)
    manifest_file = root / manifest_path
    if manifest_file.exists():
        resolved_manifest = resolve_inside(manifest_file, root)
        manifest = GraphManifest.model_validate_json(resolved_manifest.read_text(encoding="utf-8"))
        for included_path in manifest.included_paths:
            resolved = resolve_inside(root / included_path, root)
            if not resolved.is_file():
                raise ValueError(f"Graph manifest input is not a regular file: {included_path}")
            if not _excluded_snapshot_output(included_path, project):
                paths.add(included_path)
    return paths


def _record_input_paths(root: Path, directory: Path) -> set[str]:
    """List current and tracked handoff/decision Markdown files the loaders inspect."""
    paths: set[str] = set()
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", directory.as_posix()],
        cwd=root,
        capture_output=True,
        check=True,
    )
    for value in result.stdout.split(b"\0"):
        if value:
            paths.add(value.decode("utf-8"))
    location = root / directory
    if location.exists():
        resolve_inside(location, root)
        for path in location.glob("*.md"):
            resolve_inside(path, root)
            paths.add(path.relative_to(root).as_posix())
    return {path for path in paths if Path(path).name != "README.md"}


def _excluded_snapshot_output(path: str, project: ProjectConfig) -> bool:
    generated = {project.generated.current, project.generated.board}
    return path in generated or path.startswith(".superpowers/sdd/")


def _inputs_are_dirty(root: Path, paths: set[str]) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *sorted(paths)],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return bool(result.stdout)


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
    handoffs = load_latest_handoffs(root)
    decisions = load_recent_decisions(root)
    return ControlRoomState(
        project=project,
        roadmap=roadmap,
        artifacts=artifacts,
        graph_manifest=manifest,
        board_export=board_export,
        handoffs={task_id: record.header for task_id, record in handoffs.items()},
        handoff_paths={task_id: record.path for task_id, record in handoffs.items()},
        decisions={record.header.decision_id: record.header for record in decisions},
        decision_paths={record.header.decision_id: record.path for record in decisions},
        snapshot_source_revision=_snapshot_source_revision(root),
    )


def _codegraph_freshness(root: Path, state: ControlRoomState) -> str:
    if state.graph_manifest is None:
        return "Not validated: no graph manifest is present."
    try:
        validate_codegraph_freshness(root, config=state.project)
    except ValueError as error:
        if "Codegraph is stale" not in str(error):
            raise
        return "Stale: the source-tree digest differs from the manifest."
    return "Fresh: the manifest source-tree digest matches tracked inputs."


def _render_current_with_freshness(state: ControlRoomState, now: datetime, freshness: str) -> str:
    rendered = render_current(state, now)
    return rendered.replace(_codegraph_status(state), f"{_codegraph_status(state)}\n- {freshness}")


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
        f"- Snapshot input revision: `{state.snapshot_source_revision}`",
        "- Generated snapshot outputs are excluded from this revision.",
        "",
        "## Repository roadmap work",
        "",
        "| Task | Phase | Repository status | Priority | Day | Issue | Handoff |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        handoff = state.handoffs.get(item.id)
        lines.append(
            f"| {_markdown(item.id)}: {_markdown(item.title)} | "
            f"{_markdown(item.phase_id or '—')} | {item.status} | "
            f"{item.priority} | {item.day if item.day is not None else '—'} | not provisioned | "
            f"{_local_link(state.handoff_paths.get(item.id), 'handoff') if handoff else 'None'} |"
        )
    lines.extend(["", "## Phase summaries", ""])
    phase_items = [item for item in items if item.kind == "phase"]
    lines.extend(
        f"- {_markdown(item.id)}: {item.status} — {_markdown(item.title)}" for item in phase_items
    )
    if not phase_items:
        lines.append("- None recorded.")
    lines.extend(["", "## Blocked work", ""])
    blocked = [item for item in items if item.status == "blocked"]
    lines.extend(f"- {_markdown(item.id)}: {_markdown(item.blocker)}" for item in blocked)
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
    _replace_pair(
        root,
        state.project.generated.current,
        current,
        state.project.generated.board,
        board,
    )


def write_initial_snapshots(root: Path, now: datetime) -> None:
    """Write repository-only snapshots before a GitHub Project has been provisioned."""
    _timestamp(now)
    state = _load_state(root, None)
    current = _render_current_with_freshness(state, now, _codegraph_freshness(root, state))
    board = _initial_board(state, now)
    _replace_pair(
        root,
        state.project.generated.current,
        current,
        state.project.generated.board,
        board,
    )


def _prepare(root: Path, path: str, content: str) -> tuple[Path, Path]:
    destination = resolve_inside(root / path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
        handle.write(content)
        return destination, Path(handle.name)


def _replace_pair(root: Path, current_path: str, current: str, board_path: str, board: str) -> None:
    resolve_inside(root / current_path, root)
    resolve_inside(root / board_path, root)
    prepared: list[tuple[Path, Path]] = []
    try:
        prepared.append(_prepare(root, current_path, current))
        prepared.append(_prepare(root, board_path, board))
        for destination, temporary in prepared:
            temporary.replace(destination)
    except Exception:
        for _, temporary in prepared:
            temporary.unlink(missing_ok=True)
        raise
