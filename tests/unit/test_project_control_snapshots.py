from __future__ import annotations

# ruff: noqa: E501
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


def test_live_board_export_controls_current_phase_objective_and_blockers() -> None:
    """Using roadmap state despite a live export would present stale operational status."""
    state = make_control_room_state().model_copy(
        update={
            "board_export": BoardExport.model_validate(
                {
                    "project_url": "https://github.com/users/Ven-Z8/projects/1",
                    "source_revision": "b" * 40,
                    "items": [
                        {
                            "task_id": "AO-D09",
                            "title": "Live blocked objective",
                            "status": "blocked",
                            "priority": "P0",
                            "day": 9,
                            "phase_id": "AO-P4",
                            "blocker": "waiting for a live approval",
                        }
                    ],
                }
            )
        }
    )

    rendered = render_current(state, FIXED_TIME)

    assert "AO-P4 (live board)" in rendered
    assert "AO-D09: Live blocked objective" in rendered
    assert "AO-D09: waiting for a live approval" in rendered
    assert "AO-P1: Trust and Benchmark Integrity" not in rendered


def test_snapshot_writer_preserves_both_files_when_second_destination_is_a_symlink(
    tmp_path: Path,
) -> None:
    """Replacing CURRENT.md before rejecting BOARD.md would create a preventable partial update."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    current = tmp_path / "coordination/CURRENT.md"
    board = tmp_path / "coordination/BOARD.md"
    outside = tmp_path.parent / "outside-board.md"
    current.write_text("last current\n", encoding="utf-8")
    outside.write_text("last board\n", encoding="utf-8")
    board.symlink_to(outside)

    with pytest.raises(ValueError, match="without symlink"):
        write_initial_snapshots(tmp_path, FIXED_TIME)

    assert current.read_text(encoding="utf-8") == "last current\n"
    assert outside.read_text(encoding="utf-8") == "last board\n"


def test_current_and_initial_board_render_repository_record_links(tmp_path: Path) -> None:
    """Dropping record paths would make latest decisions and handoffs impossible to inspect."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    handoffs = tmp_path / "coordination/handoffs"
    handoffs.mkdir()
    handoffs.joinpath("2026-08-30-AO-D01-01-codex.md").write_text(
        "---\n"
        "schema_version: 1\ntask_id: AO-D01-01\nharness: codex\nstatus: partial\n"
        "started_at: 2026-08-30T15:00:00Z\nupdated_at: 2026-08-30T16:00:00Z\n"
        "branch: codex/AO-D01-01\nbase_commit: '1" + "1" * 39 + "'\nhead_commit: '2" + "2" * 39
        + "'\nverification: {state: not_run, commands: []}\nartifacts: []\ndecisions: []\n---\n",
        encoding="utf-8",
    )
    decisions = tmp_path / "coordination/decisions"
    decisions.mkdir()
    decisions.joinpath("ADR-001.md").write_text(
        "---\nschema_version: 1\ndecision_id: ADR-001\nstatus: accepted\n"
        "date: 2026-08-30T17:00:00Z\nowners: [codex]\ntask_ids: [AO-D01-01]\n---\n",
        encoding="utf-8",
    )

    write_initial_snapshots(tmp_path, FIXED_TIME)
    current = (tmp_path / "coordination/CURRENT.md").read_text(encoding="utf-8")
    board = (tmp_path / "coordination/BOARD.md").read_text(encoding="utf-8")

    assert "[Decision ADR-001](<coordination/decisions/ADR-001.md>)" in current
    assert "[Handoff AO-D01-01](<coordination/handoffs/2026-08-30-AO-D01-01-codex.md>)" in current
    assert "[handoff](<coordination/handoffs/2026-08-30-AO-D01-01-codex.md>)" in board


def test_snapshot_record_loading_rejects_unknown_or_malformed_handoffs(tmp_path: Path) -> None:
    """Ignoring malformed or unknown records would turn invalid evidence into an inferred pass."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    handoffs = tmp_path / "coordination/handoffs"
    handoffs.mkdir()
    handoffs.joinpath("2026-08-30-AO-UNKNOWN-codex.md").write_text(
        "---\nschema_version: 1\ntask_id: AO-UNKNOWN\n---\n", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        write_initial_snapshots(tmp_path, FIXED_TIME)

    handoffs.joinpath("2026-08-30-AO-UNKNOWN-codex.md").unlink()
    handoffs.joinpath("2026-08-30-AO-D01-01-codex.md").write_text(
        "---\nschema_version: 1\ntask_id: AO-D01-01\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="frontmatter"):
        write_initial_snapshots(tmp_path, FIXED_TIME)


def test_snapshot_provenance_separates_baseline_snapshot_and_graph_revisions() -> None:
    """Using graph provenance as the project baseline would misstate the approved source."""
    state = make_control_room_state().model_copy(
        update={"snapshot_source_revision": "c" * 40}
    )

    rendered = render_current(state, FIXED_TIME)

    assert "Baseline commit: `39c041f699d7909d1f6853a89bf2a86835a4acd4`" in rendered
    assert "Snapshot source revision: `" + "c" * 40 + "`" in rendered
    assert "Graph input provenance: unavailable" in rendered


@pytest.mark.parametrize("source_revision", ["", "arbitrary", "a" * 39])
def test_board_export_rejects_untruthful_source_revisions(source_revision: str) -> None:
    """Rendering arbitrary text as a revision would create false provenance."""
    with pytest.raises(ValidationError):
        BoardExport.model_validate(
            {
                "project_url": "https://github.com/users/Ven-Z8/projects/1",
                "source_revision": source_revision,
                "items": [],
            }
        )


def test_empty_live_export_remains_authoritative_for_current_state() -> None:
    state = make_control_room_state().model_copy(
        update={"board_export": BoardExport(project_url="https://github.com/users/Ven-Z8/projects/1", items=[])}
    )
    rendered = render_current(state, FIXED_TIME)
    assert "Unassigned (live board)" in rendered
    assert "roadmap fallback" not in rendered


def test_live_rendering_is_deterministic_and_escapes_forged_heading() -> None:
    export = BoardExport.model_validate({"project_url": "https://github.com/users/Ven-Z8/projects/1", "items": [{"task_id": "AO-D01-01", "title": "safe\n## forged", "status": "ready", "priority": "P0"}]})
    first = render_board(export, FIXED_TIME)
    assert first == render_board(export, FIXED_TIME)
    assert "\n## forged" not in first
