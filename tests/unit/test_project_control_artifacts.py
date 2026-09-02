from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.project_control.artifacts import load_artifact_index, render_artifact_summary
from app.project_control.models import ArtifactIndex, ArtifactRecord
from tests.helpers_project_control import seed_control_room


def test_required_unavailable_artifact_is_not_verified() -> None:
    with pytest.raises(ValidationError):
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


def test_load_artifact_index_validates_task_ids_and_shared_io_safety(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    index_path = tmp_path / "coordination" / "artifacts" / "index.yaml"
    index_path.parent.mkdir()
    index_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "id": "artifact-unknown",
                        "task_id": "AO-UNKNOWN",
                        "kind": "report",
                        "availability": "unavailable",
                        "locator": None,
                        "created_at": "2026-08-30T16:00:00Z",
                        "producer": "codex",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Roadmap does not include item"):
        load_artifact_index(tmp_path)

    index_path.unlink()
    target = tmp_path / "outside-index.yaml"
    target.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    index_path.symlink_to(target)
    with pytest.raises(ValueError, match="without symlink"):
        load_artifact_index(tmp_path)


def test_artifact_index_rejects_duplicate_ids_and_invalid_evidence_contracts() -> None:
    record = {
        "id": "artifact-AO-D01-01-baseline",
        "task_id": "AO-D01-01",
        "kind": "test-report",
        "availability": "repository",
        "locator": "coordination/artifacts/report.md",
        "created_at": "2026-08-30T16:00:00Z",
        "producer": "codex",
    }
    with pytest.raises(ValidationError, match="duplicate"):
        ArtifactIndex.model_validate({"schema_version": 1, "artifacts": [record, record]})

    remote = record | {"availability": "remote", "locator": "http://example.test/report"}
    with pytest.raises(ValidationError, match="durable https"):
        ArtifactRecord.model_validate(remote)

    immutable = record | {"immutable": True, "sha256": None}
    with pytest.raises(ValidationError, match="sha256"):
        ArtifactRecord.model_validate(immutable)


@pytest.mark.parametrize("sha256", [None, "not-a-sha", "a" * 63, "a" * 65])
def test_verified_artifact_requires_immutable_valid_sha256(sha256: str | None) -> None:
    record = {
        "id": "artifact-AO-D01-01-verified",
        "task_id": "AO-D01-01",
        "kind": "report",
        "availability": "repository",
        "locator": "coordination/artifacts/report.md",
        "sha256": sha256,
        "created_at": "2026-08-30T16:00:00Z",
        "producer": "codex",
        "evidence_state": "verified",
    }
    with pytest.raises(ValidationError, match="verified evidence"):
        ArtifactRecord.model_validate(record)

    record["immutable"] = True
    with pytest.raises(ValidationError, match="sha256"):
        ArtifactRecord.model_validate(record)


def test_render_artifact_summary_sorts_and_marks_local_and_unavailable_evidence() -> None:
    index = ArtifactIndex.model_validate(
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "id": "later",
                    "task_id": "AO-D01-01",
                    "kind": "report",
                    "availability": "local",
                    "locator": ".agentops/report.txt",
                    "created_at": "2026-08-30T17:00:00Z",
                    "producer": "codex",
                },
                {
                    "id": "inconclusive",
                    "task_id": "AO-D01-01",
                    "kind": "report",
                    "availability": "unavailable",
                    "locator": None,
                    "required": True,
                    "evidence_state": "missing",
                    "created_at": "2026-08-30T16:00:00Z",
                    "producer": "codex",
                },
            ],
        }
    )

    summary = render_artifact_summary(index)

    assert summary.index("## inconclusive") < summary.index("## later")
    assert "Availability: local (non-portable)" in summary
    assert "Evidence: inconclusive" in summary


def test_verification_evidence_is_strictly_validated_and_hash_addressed(tmp_path: Path) -> None:
    seed_control_room(tmp_path)
    evidence_path = tmp_path / "coordination/artifacts/task-9-verification.yaml"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        "schema_version: 1\ntask_id: AO-D01-01\nresults:\n"
        "  - command: npm test\n    exit_code: 0\n    passed: true\n"
        "    stdout: '1 test passed'\n    stderr: ''\n",
        encoding="utf-8",
    )
    import hashlib

    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (tmp_path / "coordination/artifacts/index.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "id": "artifact-AO-D02-04-task-9-verification",
                        "task_id": "AO-D01-01",
                        "kind": "verification-evidence",
                        "availability": "repository",
                        "locator": "coordination/artifacts/task-9-verification.yaml",
                        "sha256": digest,
                        "immutable": True,
                        "required": True,
                        "evidence_state": "verified",
                        "created_at": "2026-08-30T16:00:00Z",
                        "producer": "codex",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    index = load_artifact_index(tmp_path)
    assert index.artifacts[0].sha256 == digest

    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="sha256"):
        load_artifact_index(tmp_path)


@pytest.mark.parametrize(
    ("template_name", "headings"),
    [
        (
            "handoff.md",
            [
                "Objective and scope",
                "Completed work",
                "Remaining work",
                "Verification results",
                "Known risks or surprises",
                "Exact next action",
            ],
        ),
        (
            "decision.md",
            [
                "Context",
                "Decision",
                "Alternatives considered",
                "Consequences",
                "Evidence",
                "Revisit criteria",
            ],
        ),
        (
            "daily-research-memo.md",
            [
                "Research question",
                "Primary sources",
                "Findings",
                "Counter-evidence and failed attempts",
                "Decision",
                "Implementation slice",
                "Evidence produced",
                "Next-day plan",
            ],
        ),
    ],
)
def test_templates_have_exact_required_headings(template_name: str, headings: list[str]) -> None:
    template = Path("coordination/templates") / template_name
    lines = template.read_text(encoding="utf-8").splitlines()

    assert [line.removeprefix("## ") for line in lines if line.startswith("## ")] == headings
