from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.project_control.handoffs import create_handoff, latest_handoffs
from app.project_control.models import DecisionHeader, HandoffHeader
from tests.helpers_project_control import seed_control_room


def test_create_handoff_uses_stable_name_and_required_sections(tmp_path: Path) -> None:
    seed_control_room(tmp_path)

    path = create_handoff(
        tmp_path,
        task_id="AO-D01-01",
        harness="codex",
        now=datetime(2026, 8, 30, 16, tzinfo=UTC),
        branch="codex/AO-D01-01-baseline",
        base_commit="1" * 40,
        head_commit="2" * 40,
    )

    assert path.name == "2026-08-30-AO-D01-01-codex.md"
    text = path.read_text(encoding="utf-8")
    assert "status: partial" in text
    assert "## Exact next action" in text


def test_create_handoff_rejects_unknown_task_harness_and_existing_path(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    arguments = {
        "harness": "codex",
        "now": datetime(2026, 8, 30, 16, tzinfo=UTC),
        "branch": "codex/AO-D01-01-baseline",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
    }

    with pytest.raises(ValueError, match="Roadmap does not include item"):
        create_handoff(tmp_path, task_id="AO-UNKNOWN", **arguments)
    with pytest.raises(ValueError, match="harness"):
        create_handoff(tmp_path, task_id="AO-D01-01", harness="Codex", **{
            key: value for key, value in arguments.items() if key != "harness"
        })

    create_handoff(tmp_path, task_id="AO-D01-01", **arguments)
    with pytest.raises(FileExistsError):
        create_handoff(tmp_path, task_id="AO-D01-01", **arguments)


def test_create_handoff_uses_shared_io_for_symlinked_handoff_directory(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    outside = tmp_path.parent / "outside-handoffs"
    outside.mkdir(exist_ok=True)
    (tmp_path / "coordination" / "handoffs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="without symlink"):
        create_handoff(
            tmp_path,
            task_id="AO-D01-01",
            harness="codex",
            now=datetime(2026, 8, 30, 16, tzinfo=UTC),
            branch="codex/AO-D01-01-baseline",
            base_commit="1" * 40,
            head_commit="2" * 40,
        )


def test_latest_handoffs_uses_updated_at_then_path_name_ordering(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    handoffs = tmp_path / "coordination" / "handoffs"
    handoffs.mkdir()
    first = handoffs / "2026-08-30-AO-D01-01-zulu.md"
    second = handoffs / "2026-08-30-AO-D01-01-alpha.md"
    third = handoffs / "2026-08-30-AO-D01-01-bravo.md"

    for path, updated_at in (
        (first, "2026-08-30T16:00:00Z"),
        (second, "2026-08-30T17:00:00Z"),
        (third, "2026-08-30T17:00:00Z"),
    ):
        payload = {
            "schema_version": 1,
            "task_id": "AO-D01-01",
            "harness": "codex",
            "status": "partial",
            "started_at": "2026-08-30T15:00:00Z",
            "updated_at": updated_at,
            "branch": "codex/AO-D01-01",
            "base_commit": "1" * 40,
            "head_commit": "2" * 40,
            "verification": {"state": "not_run", "commands": []},
            "artifacts": [],
            "decisions": [],
        }
        path.write_text(f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\n", encoding="utf-8")

    assert latest_handoffs(tmp_path) == {"AO-D01-01": third}


def test_latest_handoffs_rejects_unknown_task_and_symlinked_record(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    handoffs = tmp_path / "coordination" / "handoffs"
    handoffs.mkdir()
    payload = {
        "schema_version": 1,
        "task_id": "AO-UNKNOWN",
        "harness": "codex",
        "status": "partial",
        "started_at": "2026-08-30T15:00:00Z",
        "updated_at": "2026-08-30T16:00:00Z",
        "branch": "codex/AO-D01-01",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
        "verification": {"state": "not_run", "commands": []},
        "artifacts": [],
        "decisions": [],
    }
    invalid = handoffs / "2026-08-30-AO-UNKNOWN-codex.md"
    invalid.write_text(f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Roadmap does not include item"):
        latest_handoffs(tmp_path)

    invalid.unlink()
    target = tmp_path / "valid-handoff.md"
    target.write_text("---\nschema_version: 1\n---\n", encoding="utf-8")
    (handoffs / "2026-08-30-AO-D01-01-codex.md").symlink_to(target)
    with pytest.raises(ValueError, match="without symlink"):
        latest_handoffs(tmp_path)


def test_handoff_and_decision_terminal_semantics_reject_invalid_states() -> None:
    handoff = {
        "schema_version": 1,
        "task_id": "AO-D01-01",
        "harness": "codex",
        "status": "completed",
        "started_at": "2026-08-30T16:00:00Z",
        "updated_at": "2026-08-30T15:00:00Z",
        "branch": "codex/AO-D01-01",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
        "verification": {"required": False, "state": "passed", "commands": []},
    }
    with pytest.raises(ValidationError, match="updated_at"):
        HandoffHeader.model_validate(handoff)

    decision = {
        "schema_version": 1,
        "decision_id": "ADR-001",
        "status": "accepted",
        "date": "2026-08-30T16:00:00Z",
        "owners": ["codex"],
        "task_ids": ["AO-D01-01"],
        "superseding_decision_id": "ADR-002",
    }
    with pytest.raises(ValidationError, match="only superseded"):
        DecisionHeader.model_validate(decision)
