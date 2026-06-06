from __future__ import annotations

from pathlib import Path

from app.prompts.integrations import CURSOR_FILES, GOOSE_RECIPE
from app.prompts.planner import build_planner_prompt
from app.prompts.pr_writer import build_pr_writer_prompt, format_edit_summary
from app.prompts.reviewer import build_reviewer_prompt
from app.prompts.workers import build_worker_prompt
from app.schemas.edit import ExternalEditResult
from app.schemas.plan import ImplementationPlan
from app.schemas.repo import RepoProfile
from app.schemas.review import ReviewFinding, ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


def test_planner_prompt_includes_repo_context_and_memory() -> None:
    prompt = build_planner_prompt(
        task="Add request logging middleware",
        repo_profile=RepoProfile(
            repo_path="/repo",
            language="python",
            framework="fastapi",
            package_manager="uv",
            test_framework="pytest",
            entrypoints=["app/main.py"],
            config_files=["pyproject.toml"],
            source_files=["app/main.py", "tests/test_health.py"],
        ),
        memory_lessons=["Previous middleware edits need route tests."],
    )

    assert "Planner Agent" in prompt
    assert "Add request logging middleware" in prompt
    assert "FastAPI" in prompt
    assert "app/main.py" in prompt
    assert "Previous middleware edits need route tests." in prompt


def test_reviewer_prompt_includes_changed_files_and_validation_output() -> None:
    prompt = build_reviewer_prompt(
        changed_files=["app/main.py"],
        test_results=TestRunSummary(
            commands=[
                CommandResult(
                    command="python -m pytest -q",
                    exit_code=1,
                    duration_seconds=0.25,
                    stdout="failed assertion",
                    stderr="traceback",
                )
            ]
        ),
    )

    assert "Reviewer Agent" in prompt
    assert "app/main.py" in prompt
    assert "python -m pytest -q" in prompt
    assert "failed assertion" in prompt
    assert "traceback" in prompt


def test_pr_writer_prompt_includes_report_inputs() -> None:
    prompt = build_pr_writer_prompt(
        task="Add middleware",
        plan=ImplementationPlan(
            task="Add middleware",
            summary="Add middleware to app startup.",
            acceptance_criteria=["Requests are logged."],
        ),
        changed_files=["app/main.py"],
        test_results=TestRunSummary(
            commands=[
                CommandResult(command="python -m pytest -q", exit_code=0, duration_seconds=0.1)
            ]
        ),
        review_report=ReviewReport(
            summary="Review completed.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    title="Route coverage",
                    description="Middleware affects routes.",
                    recommendation="Add route-level tests.",
                )
            ],
        ),
        risk_report=RiskReport(risk_score=24, risk_level="low", factors=["Small change"]),
    )

    assert "PR Writer Agent" in prompt
    assert "Add middleware to app startup." in prompt
    assert "Requests are logged." in prompt
    assert "Route coverage" in prompt
    assert "Small change" in prompt


def test_worker_prompt_is_shared_by_external_workers() -> None:
    prompt = build_worker_prompt(repo_path=Path("/repo"), task="Add logging")

    assert "coding agent" in prompt
    assert "/repo" in prompt
    assert "Task: Add logging" in prompt
    assert "run tests" in prompt


def test_format_edit_summary_handles_observe_and_external_worker_modes() -> None:
    assert format_edit_summary(None) == "## Edit mode\n- Mode: observe-only"

    summary = format_edit_summary(
        ExternalEditResult(
            status="completed",
            command="codex exec",
            exit_code=0,
            duration_seconds=1.25,
        )
    )

    assert "Mode: external worker" in summary
    assert "codex exec" in summary
    assert "1.250s" in summary


def test_integration_prompt_templates_live_in_prompt_package() -> None:
    assert ".cursor/rules/agentops-harness.mdc" in CURSOR_FILES
    assert "AgentOps Harness Cursor Rules" in CURSOR_FILES[".cursor/rules/agentops-harness.mdc"]
    assert "prompt: |" in GOOSE_RECIPE
    assert "Evaluate this engineering task with AgentOps Harness" in GOOSE_RECIPE
