from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.handoff import (
    draft_worker_handoff,
    handoff_document_json,
    render_handoff_markdown,
    worker_handoff_from_run,
)
from app.schemas.edit import ExternalEditResult
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import CommandResult, TestRunSummary


def _minimal_run(*, edit: ExternalEditResult | None = None) -> RunRecord:
    plan = ImplementationPlan(
        task="Add middleware",
        summary="Summary line",
        steps=[
            PlanStep(
                id=1,
                title="Implement",
                description="Do the thing",
                files_to_inspect=["app/main.py"],
                files_to_edit=["app/logging.py"],
            )
        ],
        acceptance_criteria=["Logs include request ids"],
        tests_to_run=["python -m pytest -q"],
    )
    return RunRecord(
        run_id="abc123",
        task=plan.task,
        repo_path="/tmp/repo",
        repo_profile=RepoProfile(repo_path="/tmp/repo"),
        plan=plan,
        changed_files=["app/logging.py"],
        deleted_files=[],
        diff_summary="+1",
        test_results=TestRunSummary(
            commands=[
                CommandResult(
                    command="python -m pytest -q",
                    exit_code=0,
                    duration_seconds=0.1,
                )
            ]
        ),
        review_report=ReviewReport(summary="ok", findings=[]),
        risk_report=RiskReport(risk_score=20, risk_level="low"),
        final_report=FinalReport(title="r", markdown="# hi"),
        edit_result=edit,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def test_worker_handoff_includes_commands_and_constraints() -> None:
    packet = worker_handoff_from_run(_minimal_run())
    markdown = render_handoff_markdown(packet)
    payload = handoff_document_json(packet)

    assert "python -m pytest -q" in markdown
    assert packet.verification_commands == ["python -m pytest -q"]
    assert payload["constraints"]
    assert payload["markdown"].startswith("# Worker handoff")


def test_draft_handoff_flags_pending(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    (repo_path / "app.py").write_text("print('x')\n")
    packet = draft_worker_handoff(repo_path=repo_path, task="Improve logging")

    assert packet.phase == "draft_pre_worker"
    assert packet.harness_status == "pending_verification"
    rendered = render_handoff_markdown(packet)
    assert "Draft (pre-worker)" in rendered


def test_draft_handoff_uses_graph_aware_plan() -> None:
    repo_path = Path("examples/sample_fastapi_app")
    packet = draft_worker_handoff(repo_path=repo_path, task="Add a route")

    assert "uv run pytest -q" in packet.tests_to_run
    inspected = {path for step in packet.plan_steps for path in step.files_to_inspect}
    assert "app/main.py" in inspected


def test_handoff_documents_external_edit_status_when_present() -> None:
    record = _minimal_run(edit=ExternalEditResult(status="completed", command="codex exec"))
    markdown = render_handoff_markdown(worker_handoff_from_run(record))
    assert "external worker" in markdown
