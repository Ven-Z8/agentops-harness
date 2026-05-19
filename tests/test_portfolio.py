from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.core.portfolio import build_portfolio_episode, render_portfolio_episode_markdown
from app.core.storage import RunStorage
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import CommandResult, TestRunSummary
from app.schemas.workload import WorkloadExpected, WorkloadManifest


def _portfolio_run() -> RunRecord:
    plan = ImplementationPlan(
        task="Validate ContextIQ hardcoding audit",
        summary="Run the hardcoding audit and package evidence.",
        steps=[
            PlanStep(
                id=1,
                title="Run focused checks",
                description="Execute the audit tests and review the result.",
                files_to_inspect=["tests/unit/test_no_corpus_hardcoding.py"],
                files_to_edit=[],
            )
        ],
        acceptance_criteria=["Audit command passes"],
        tests_to_run=["uv run --extra dev pytest tests/unit/test_no_corpus_hardcoding.py -q"],
    )
    return RunRecord(
        run_id="episode-1",
        task=plan.task,
        repo_path="/workspace/projects/contextiq",
        repo_profile=RepoProfile(repo_path="/workspace/projects/contextiq"),
        plan=plan,
        changed_files=["tests/unit/test_no_corpus_hardcoding.py"],
        deleted_files=[],
        diff_summary="+ audit evidence",
        test_results=TestRunSummary(
            commands=[
                CommandResult(
                    command="uv run --extra dev pytest tests/unit/test_no_corpus_hardcoding.py -q",
                    exit_code=0,
                    duration_seconds=0.42,
                )
            ]
        ),
        review_report=ReviewReport(summary="No blocking findings.", findings=[]),
        risk_report=RiskReport(risk_score=20, risk_level="low"),
        final_report=FinalReport(title="ContextIQ audit", markdown="# ContextIQ audit\n\nPassed."),
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def test_portfolio_episode_renders_run_signals() -> None:
    workload = WorkloadManifest(
        name="ContextIQ Hardcoding Audit",
        repo="../contextiq",
        task="Validate ContextIQ hardcoding audit",
        expected=WorkloadExpected(
            max_risk_score=30,
            required_commands=[
                "uv run --extra dev pytest tests/unit/test_no_corpus_hardcoding.py -q"
            ],
        ),
    )
    episode = build_portfolio_episode(_portfolio_run(), workload)
    markdown = render_portfolio_episode_markdown(episode)

    assert "Portfolio Episode: ContextIQ Hardcoding Audit" in markdown
    assert "Workload gates: passed" in markdown
    assert "Risk score: 20 (low)" in markdown
    assert "tests/unit/test_no_corpus_hardcoding.py" in markdown


def test_cli_packages_portfolio_episode_to_file(tmp_path: Path) -> None:
    storage_path = tmp_path / "runs.jsonl"
    RunStorage(storage_path).save(_portfolio_run())
    workload_path = tmp_path / "workload.yaml"
    workload_path.write_text(
        "\n".join(
            [
                "name: ContextIQ Hardcoding Audit",
                "repo: ../contextiq",
                "task: Validate ContextIQ hardcoding audit",
                "expected:",
                "  max_risk_score: 30",
                "  required_commands:",
                "    - uv run --extra dev pytest tests/unit/test_no_corpus_hardcoding.py -q",
                "",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "episode.md"

    result = CliRunner().invoke(
        app,
        [
            "portfolio",
            "package",
            "--run-id",
            "episode-1",
            "--storage",
            str(storage_path),
            "--workload",
            str(workload_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    assert "Portfolio Episode: ContextIQ Hardcoding Audit" in output_path.read_text()
