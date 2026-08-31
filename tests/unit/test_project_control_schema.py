from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.project_control.io import atomic_write, load_frontmatter, load_yaml
from app.project_control.models import (
    ArtifactRecord,
    GraphManifest,
    HandoffHeader,
    ProjectConfig,
    Roadmap,
)
from tests.helpers_project_control import valid_project_config, valid_roadmap_item


def test_project_config_rejects_unknown_keys(tmp_path: Path) -> None:
    payload = valid_project_config()
    payload["unknown"] = True
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_yaml(path, ProjectConfig, root=tmp_path)


def test_roadmap_rejects_duplicate_ids() -> None:
    payload = {
        "schema_version": 1,
        "roadmap_id": "AO-14D",
        "items": [valid_roadmap_item("AO-D01"), valid_roadmap_item("AO-D01")],
    }

    with pytest.raises(ValidationError, match="duplicate"):
        Roadmap.model_validate(payload)


def test_roadmap_rejects_missing_dependency() -> None:
    item = valid_roadmap_item("AO-D01")
    item["dependencies"] = ["AO-X"]
    payload = {"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]}

    with pytest.raises(ValidationError, match="unknown dependency"):
        Roadmap.model_validate(payload)


def test_load_yaml_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("schema_version: 1\n", encoding="utf-8")
    link = tmp_path / "linked.yaml"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="without symlink"):
        load_yaml(link, ProjectConfig, root=tmp_path)


def test_load_yaml_rejects_parent_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-project.yaml"
    outside.write_text(yaml.safe_dump(valid_project_config()), encoding="utf-8")

    with pytest.raises(ValueError, match="inside repository"):
        load_yaml(tmp_path / ".." / outside.name, ProjectConfig, root=tmp_path)


def test_atomic_write_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside repository"):
        atomic_write(tmp_path / ".." / "outside.md", "nope\n", root=tmp_path)


def test_atomic_write_creates_an_in_root_file(tmp_path: Path) -> None:
    destination = tmp_path / "coordination" / "CURRENT.md"

    atomic_write(destination, "current\n", root=tmp_path)

    assert destination.read_text(encoding="utf-8") == "current\n"


def test_roadmap_rejects_self_dependencies() -> None:
    item = valid_roadmap_item("AO-D01")
    item["dependencies"] = ["AO-D01"]

    with pytest.raises(ValidationError, match="self-dependency"):
        Roadmap.model_validate({"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]})


def test_roadmap_rejects_dependency_cycles() -> None:
    first = valid_roadmap_item("AO-D01")
    second = valid_roadmap_item("AO-D02")
    first["dependencies"] = ["AO-D02"]
    second["dependencies"] = ["AO-D01"]

    with pytest.raises(ValidationError, match="cycle"):
        Roadmap.model_validate(
            {"schema_version": 1, "roadmap_id": "AO-14D", "items": [first, second]}
        )


def test_load_frontmatter_rejects_missing_closing_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text("---\nschema_version: 1\n", encoding="utf-8")

    with pytest.raises(Exception, match="handoff.md"):
        load_frontmatter(path, HandoffHeader, root=tmp_path)


def test_completed_handoff_with_required_verification_rejects_non_passing_state() -> None:
    payload = {
        "schema_version": 1,
        "task_id": "AO-D01-01",
        "harness": "codex",
        "status": "completed",
        "started_at": "2026-08-30T15:00:00Z",
        "updated_at": "2026-08-30T16:00:00Z",
        "branch": "codex/AO-D01-01",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
        "verification": {"required": True, "state": "not_run", "commands": []},
        "artifacts": [],
        "decisions": [],
    }

    for state in ("not_run", "partial", "failed"):
        payload["verification"] = {"required": True, "state": state, "commands": []}
        with pytest.raises(ValidationError, match="passed"):
            HandoffHeader.model_validate(payload)


def test_blocked_handoff_requires_blocker_and_authority() -> None:
    payload = {
        "schema_version": 1,
        "task_id": "AO-D01-01",
        "harness": "codex",
        "status": "blocked",
        "started_at": "2026-08-30T15:00:00Z",
        "updated_at": "2026-08-30T16:00:00Z",
        "branch": "codex/AO-D01-01",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
        "verification": {"required": False, "state": "not_run", "commands": []},
        "artifacts": [],
        "decisions": [],
    }

    with pytest.raises(ValidationError, match="blocker"):
        HandoffHeader.model_validate(payload)


def test_required_unavailable_artifact_cannot_claim_verified_evidence() -> None:
    with pytest.raises(ValidationError, match="unavailable"):
        ArtifactRecord.model_validate(
            {
                "id": "artifact-AO-D01-01-baseline",
                "task_id": "AO-D01-01",
                "kind": "test-report",
                "availability": "unavailable",
                "locator": None,
                "required": True,
                "evidence_state": "verified",
                "created_at": "2026-08-30T16:00:00Z",
                "producer": "codex",
            }
        )


def test_handoff_requires_full_commit_identifiers() -> None:
    payload = {
        "schema_version": 1,
        "task_id": "AO-D01-01",
        "harness": "codex",
        "status": "partial",
        "started_at": "2026-08-30T15:00:00Z",
        "updated_at": "2026-08-30T16:00:00Z",
        "branch": "codex/AO-D01-01",
        "base_commit": "deadbeef",
        "head_commit": "2" * 40,
        "verification": {"required": False, "state": "not_run", "commands": []},
        "artifacts": [],
        "decisions": [],
    }

    with pytest.raises(ValidationError):
        HandoffHeader.model_validate(payload)


@pytest.mark.parametrize("field_name", ["likely_files", "source_documents"])
@pytest.mark.parametrize("invalid_path", ["/etc/passwd", "coordination/../escape", "./design.md"])
def test_roadmap_rejects_non_normalized_repository_path_lists(
    field_name: str, invalid_path: str
) -> None:
    item = valid_roadmap_item("AO-D01")
    item[field_name] = [invalid_path]

    with pytest.raises(ValidationError, match="repository path"):
        Roadmap.model_validate({"schema_version": 1, "roadmap_id": "AO-14D", "items": [item]})


@pytest.mark.parametrize("invalid_path", ["/etc/passwd", "coordination/../escape", "./design.md"])
def test_graph_manifest_rejects_non_normalized_included_paths(invalid_path: str) -> None:
    payload = {
        "schema_version": 1,
        "generator_version": "1",
        "source_commit": "a" * 40,
        "source_tree_digest": "b" * 64,
        "included_paths": [invalid_path],
        "exclusions": [],
        "counts": {},
        "generated_at": "2026-08-30T16:00:00Z",
        "language_coverage": {},
    }

    with pytest.raises(ValidationError, match="repository path"):
        GraphManifest.model_validate(payload)
