from __future__ import annotations

from pathlib import Path

import yaml


def valid_project_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": {
            "id": "agentops-harness",
            "name": "AgentOps Research Control Plane",
            "repository": "Ven-Z8/agentops-harness",
            "default_branch": "main",
        },
        "roadmap": {"id": "AO-14D", "source": "coordination/roadmap/14-day-plan.yaml"},
        "github_project": {"owner": "Ven-Z8", "number": None, "url": None},
        "generated": {
            "board": "coordination/BOARD.md",
            "current": "coordination/CURRENT.md",
            "codegraph": "coordination/codegraph",
        },
    }


def valid_roadmap_item(task_id: str) -> dict[str, object]:
    return {
        "id": task_id,
        "title": "Truthful terminal states and strict boundaries",
        "kind": "task",
        "day": 1,
        "phase_id": "AO-P1",
        "parent_id": "AO-D01",
        "status": "planned",
        "maturity": "confirmed",
        "priority": "P0",
        "risk": "critical",
        "blocker": "phase",
        "outcome": "Terminal states are truthful.",
        "scope": ["Reject invalid state."],
        "non_goals": ["Change AgentOps runtime behavior."],
        "dependencies": [],
        "acceptance_criteria": ["Validation fails closed."],
        "required_evidence": ["Focused test output."],
        "likely_files": ["app/project_control/models.py"],
        "test_first": "tests/unit/test_project_control_schema.py",
        "terminal_semantics": "Invalid state is rejected.",
        "compatibility": "Additive coordination-only schema.",
        "verification_commands": ["uv run pytest tests/unit/test_project_control_schema.py -q"],
        "risks": ["False success."],
        "rollback": "Revert this task slice.",
        "source_documents": ["coordination/designs/2026-08-30-project-control-room-design.md"],
        "github": {"issue_number": None, "issue_url": None},
    }


def seed_control_room(root: Path) -> None:
    project = root / "coordination" / "project.yaml"
    roadmap = root / "coordination" / "roadmap" / "14-day-plan.yaml"
    project.parent.mkdir(parents=True, exist_ok=True)
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    project.write_text(yaml.safe_dump(valid_project_config()), encoding="utf-8")
    roadmap_payload = {
        "schema_version": 1,
        "roadmap_id": "AO-14D",
        "items": [valid_roadmap_item("AO-D01-01")],
    }
    roadmap.write_text(
        yaml.safe_dump(roadmap_payload),
        encoding="utf-8",
    )


def make_control_room_state():
    from app.project_control.models import ControlRoomState, ProjectConfig, Roadmap

    roadmap_payload = {
        "schema_version": 1,
        "roadmap_id": "AO-14D",
        "items": [valid_roadmap_item("AO-D01-01")],
    }
    return ControlRoomState(
        project=ProjectConfig.model_validate(valid_project_config()),
        roadmap=Roadmap.model_validate(roadmap_payload),
    )
