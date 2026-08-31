from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.project_control.io import atomic_write, load_frontmatter, resolve_inside
from app.project_control.models import HandoffHeader
from app.project_control.roadmap import load_roadmap

_HARNESS_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_HANDOFF_SECTIONS = (
    "Objective and scope",
    "Completed work",
    "Remaining work",
    "Verification results",
    "Known risks or surprises",
    "Exact next action",
)


@dataclass(frozen=True)
class HandoffRecord:
    header: HandoffHeader
    path: str


def _require_roadmap_task(root: Path, task_id: str) -> None:
    if not any(item.id == task_id for item in load_roadmap(root).items):
        raise ValueError(f"Roadmap does not include item: {task_id}")


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expected_handoff_name(header: HandoffHeader) -> str:
    if header.started_at.tzinfo is None or header.started_at.utcoffset() is None:
        raise ValueError("Handoff filename requires timezone-aware started_at")
    created_on = header.started_at.astimezone(UTC).date().isoformat()
    return f"{created_on}-{header.task_id}-{header.harness}.md"


def create_handoff(
    root: Path,
    task_id: str,
    harness: str,
    now: datetime,
    branch: str,
    base_commit: str,
    head_commit: str,
) -> Path:
    """Create an initial, intentionally partial handoff for a roadmap item."""
    _require_roadmap_task(root, task_id)
    if not _HARNESS_SLUG.fullmatch(harness):
        raise ValueError("harness must be a lowercase slug of up to 32 characters")

    timestamp = _utc_timestamp(now)
    path = root / "coordination" / "handoffs" / f"{timestamp[:10]}-{task_id}-{harness}.md"
    resolved = resolve_inside(path, root)
    if resolved.exists():
        raise FileExistsError(f"Refusing to overwrite existing handoff: {path}")

    header = HandoffHeader.model_validate(
        {
            "schema_version": 1,
            "task_id": task_id,
            "harness": harness,
            "status": "partial",
            "started_at": timestamp,
            "updated_at": timestamp,
            "branch": branch,
            "base_commit": base_commit,
            "head_commit": head_commit,
            "verification": {"required": False, "state": "not_run", "commands": []},
            "artifacts": [],
            "decisions": [],
        }
    )
    frontmatter = yaml.safe_dump(
        header.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    ).rstrip()
    content = "\n".join(
        [
            "---",
            frontmatter,
            "---",
            "",
            *[f"## {section}\nNot yet recorded.\n" for section in _HANDOFF_SECTIONS],
        ]
    )
    atomic_write(path, content, root=root)
    return path


def latest_handoffs(root: Path) -> dict[str, Path]:
    """Return the newest valid handoff per task, ordered by schema timestamps."""
    latest: dict[str, tuple[datetime, Path]] = {}
    handoffs_directory = root / "coordination" / "handoffs"
    if not handoffs_directory.exists():
        return {}
    resolve_inside(handoffs_directory, root)

    for path in sorted(handoffs_directory.glob("*.md")):
        if path.name == "README.md":
            continue
        header = load_frontmatter(path, HandoffHeader, root=root)
        expected_name = _expected_handoff_name(header)
        if path.name != expected_name:
            raise ValueError(
                f"Handoff filename does not match header: expected {expected_name}, got {path.name}"
            )
        _require_roadmap_task(root, header.task_id)
        candidate = (header.updated_at, path.name)
        previous = latest.get(header.task_id)
        if previous is None or candidate > (previous[0], previous[1].name):
            latest[header.task_id] = (header.updated_at, path)
    return {task_id: record[1] for task_id, record in latest.items()}


def load_latest_handoffs(root: Path) -> dict[str, HandoffRecord]:
    """Return latest validated handoffs with normalized repository-relative paths."""
    return {
        task_id: HandoffRecord(load_frontmatter(path, HandoffHeader, root=root), path.relative_to(root).as_posix())
        for task_id, path in latest_handoffs(root).items()
    }
