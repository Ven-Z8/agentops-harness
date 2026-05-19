from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from typer.testing import CliRunner

from app.cli import app
from app.core.storage import RunStorage
from app.core.workload import evaluate_workload_gates, load_workload_manifest
from app.schemas.plan import ImplementationPlan
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import CommandResult, TestRunSummary


def test_load_manifest_from_disk(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workload.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "repo": "examples/mock",
                "task": "Do work",
                "expected": {
                    "max_risk_score": 40,
                    "required_commands": ["python -m pytest -q"],
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = load_workload_manifest(manifest_path)

    assert manifest.name == "demo"
    assert manifest.expected.max_risk_score == 40


def test_workload_gates_pass_and_fail_reasons(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workload.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "name": "gates",
                "repo": "repo",
                "task": "t",
                "expected": {
                    "max_risk_score": 30,
                    "required_commands": ["python -m pytest -q"],
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = load_workload_manifest(manifest_path)

    ok_record = RunRecord(
        run_id="1",
        task="x",
        repo_path="/r",
        repo_profile=RepoProfile(repo_path="/r"),
        plan=ImplementationPlan(task="x", summary="s"),
        test_results=TestRunSummary(
            commands=[
                CommandResult(command="python -m pytest -q", exit_code=0, duration_seconds=0.1)
            ]
        ),
        review_report=ReviewReport(summary="ok", findings=[]),
        risk_report=RiskReport(risk_score=25, risk_level="medium"),
        final_report=FinalReport(title="t", markdown="m"),
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    failing_risk = ok_record.model_copy(
        deep=True,
        update={"risk_report": RiskReport(risk_score=999, risk_level="critical")},
    )

    missing_cmd = ok_record.model_copy(
        deep=True,
        update={
            "test_results": TestRunSummary(
                commands=[CommandResult(command="ruff check .", exit_code=0, duration_seconds=0.05)]
            )
        },
    )

    assert evaluate_workload_gates(ok_record, manifest).passed is True
    assert evaluate_workload_gates(failing_risk, manifest).passed is False
    assert evaluate_workload_gates(missing_cmd, manifest).passed is False


def test_cli_workload_check_outputs_gate_result(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workload.yaml"
    required_command = "python -m pytest -q"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "name": "cli gates",
                "repo": "repo",
                "task": "t",
                "expected": {
                    "max_risk_score": 30,
                    "required_commands": [required_command],
                },
            }
        ),
        encoding="utf-8",
    )
    storage_path = tmp_path / "runs.jsonl"
    record = RunRecord(
        run_id="cli-run",
        task="x",
        repo_path="/r",
        repo_profile=RepoProfile(repo_path="/r"),
        plan=ImplementationPlan(task="x", summary="s"),
        test_results=TestRunSummary(
            commands=[CommandResult(command=required_command, exit_code=0, duration_seconds=0.1)]
        ),
        review_report=ReviewReport(summary="ok", findings=[]),
        risk_report=RiskReport(risk_score=25, risk_level="medium"),
        final_report=FinalReport(title="t", markdown="m"),
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    RunStorage(storage_path).save(record)

    result = CliRunner().invoke(
        app,
        [
            "workload",
            "check",
            str(manifest_path),
            "--run-id",
            "cli-run",
            "--storage",
            str(storage_path),
        ],
    )

    assert result.exit_code == 0
    assert '"passed": true' in result.output
