"""Validated discovery of repository decision records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.project_control.io import load_frontmatter, resolve_inside
from app.project_control.models import DecisionHeader
from app.project_control.roadmap import load_roadmap


@dataclass(frozen=True)
class DecisionRecord:
    header: DecisionHeader
    path: str


def load_recent_decisions(root: Path) -> list[DecisionRecord]:
    directory = root / "coordination" / "decisions"
    if not directory.exists():
        return []
    resolve_inside(directory, root)
    task_ids = {item.id for item in load_roadmap(root).items}
    records: list[DecisionRecord] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        header = load_frontmatter(path, DecisionHeader, root=root)
        unknown = sorted(set(header.task_ids) - task_ids)
        if unknown:
            raise ValueError(f"Roadmap does not include item: {unknown[0]}")
        records.append(DecisionRecord(header, path.relative_to(root).as_posix()))
    return sorted(records, key=lambda record: (record.header.date, record.header.decision_id), reverse=True)
