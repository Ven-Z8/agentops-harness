from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.project_control.models import BoardExport
from app.project_control.snapshots import (
    render_board,
    render_current,
    write_initial_snapshots,
    write_snapshots,
)
from tests.helpers_project_control import make_control_room_state, seed_control_room

FIXED_TIME = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def test_board_snapshot_declares_live_authority() -> None:
    """Removing the generated/authority banner would make offline state misleading."""
    export = BoardExport(project_url="https://github.com/users/Ven-Z8/projects/1", items=[])

    rendered = render_board(export, datetime(2026, 8, 30, 17, tzinfo=UTC))

    assert "Generated snapshot; do not edit manually" in rendered
    assert "GitHub Issues and Projects are authoritative for live execution state" in rendered


def test_board_snapshot_sorts_live_work_by_execution_priority() -> None:
    """Changing the declared sort key would put less urgent live work first."""
    export = BoardExport.model_validate(
        {
            "project_url": "https://github.com/users/Ven-Z8/projects/1",
            "source_revision": "a" * 40,
            "items": [
                {
                    "task_id": "AO-D02-01",
                    "title": "Ready P0",
                    "status": "ready",
                    "priority": "P0",
                    "day": 2,
                },
                {
                    "task_id": "AO-D01-02",
                    "title": "Blocked P3",
                    "status": "blocked",
                    "priority": "P3",
                    "day": 1,
                },
                {
                    "task_id": "AO-D01-01",
                    "title": "Blocked P0",
                    "status": "blocked",
                    "priority": "P0",
                    "day": 1,
                },
            ],
        }
    )

    rendered = render_board(export, FIXED_TIME)

    assert rendered.index("AO-D01-01") < rendered.index("AO-D01-02") < rendered.index("AO-D02-01")


def test_current_snapshot_exposes_required_onboarding_context() -> None:
    """Dropping current-state sections would leave a new agent without required context."""
    rendered = render_current(make_control_room_state(), FIXED_TIME)

    assert "## Current phase" in rendered
    assert "## Immediate objective" in rendered
    assert "## Confirmed baseline" in rendered
    assert "Baseline commit:" in rendered
    assert "## Active blockers" in rendered
    assert "## Latest decisions and handoffs" in rendered
    assert "## Code graph freshness" in rendered
    assert "uv run python scripts/project_control.py validate" in rendered


def test_invalid_export_does_not_replace_last_good_board(tmp_path: Path) -> None:
    """Skipping validation before write would destroy the last usable board snapshot."""
    board = tmp_path / "coordination/BOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text("last good\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        write_snapshots(tmp_path, {"invalid": True}, FIXED_TIME)

    assert board.read_text(encoding="utf-8") == "last good\n"


def test_initial_snapshots_are_stable_and_identify_unprovisioned_project(tmp_path: Path) -> None:
    """A clock-dependent or live-state claim would make repository snapshots non-repeatable."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")

    write_initial_snapshots(tmp_path, FIXED_TIME)
    first = {
        name: (tmp_path / "coordination" / name).read_bytes()
        for name in ("CURRENT.md", "BOARD.md")
    }
    write_initial_snapshots(tmp_path, FIXED_TIME)
    second = {
        name: (tmp_path / "coordination" / name).read_bytes()
        for name in ("CURRENT.md", "BOARD.md")
    }

    assert first == second
    assert b"GitHub project: not provisioned" in first["BOARD.md"]
    assert b"AO-D01-01" in first["BOARD.md"]
    assert b"## Blocked work" in first["BOARD.md"]
    assert b"## Harness assignments" in first["BOARD.md"]
