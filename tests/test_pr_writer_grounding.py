from app.agents.evidence_guard import EvidenceGuard
from app.agents.pr_writer import PRWriter
from app.core.repo_graph.impact import (
    ChangedSubgraph,
    ImpactedValidation,
    render_changed_subgraph_markdown,
)
from app.prompts.pr_writer import build_pr_writer_prompt
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


def sample_plan() -> ImplementationPlan:
    return ImplementationPlan(
        task="Add request logging middleware",
        summary="Implement 'Add request logging middleware' in the detected FastAPI project.",
        steps=[
            PlanStep(
                id=1,
                title="Plan middleware",
                description="Plan request logging middleware and tests.",
            )
        ],
        acceptance_criteria=["Request logging behavior is covered."],
        tests_to_run=["python -m pytest -q", "ruff check ."],
    )


def sample_review() -> ReviewReport:
    return ReviewReport(summary="No review findings.", findings=[])


def sample_risk() -> RiskReport:
    return RiskReport(risk_score=10, risk_level="low", factors=["Small diff"])


def command(cmd: str, exit_code: int) -> CommandResult:
    return CommandResult(
        command=cmd,
        exit_code=exit_code,
        duration_seconds=0.1,
        stdout="",
        stderr="",
    )


def write_report(
    changed_files: list[str],
    test_results: TestRunSummary,
) -> FinalReport:
    return PRWriter().write(
        task="Add request logging middleware",
        plan=sample_plan(),
        changed_files=changed_files,
        test_results=test_results,
        review_report=sample_review(),
        risk_report=sample_risk(),
    )


def test_pr_writer_states_analysis_only_when_no_files_changed() -> None:
    report = write_report(
        changed_files=[],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 0)]),
    )

    assert "analysis-only run: no files were changed" in report.markdown.lower()


def test_pr_writer_states_validation_passed_only_when_all_commands_passed() -> None:
    report = write_report(
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 0)]),
    )

    assert "all executed validation commands passed" in report.markdown.lower()


def test_pr_writer_states_validation_failed_when_any_command_failed() -> None:
    report = write_report(
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 1)]),
    )

    lowered = report.markdown.lower()
    assert "validation failed" in lowered
    assert "all executed validation commands passed" not in lowered


def test_pr_writer_states_when_no_validation_commands_were_executed() -> None:
    report = write_report(
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[]),
    )

    assert "no validation commands were executed" in report.markdown.lower()


def test_pr_writer_prompt_includes_grounding_rules() -> None:
    prompt = build_pr_writer_prompt(
        task="Add request logging middleware",
        plan=sample_plan(),
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 0)]),
        review_report=sample_review(),
        risk_report=sample_risk(),
    )

    assert "Grounding rules" in prompt
    assert "Only describe a command as executed" in prompt
    assert "analysis-only" in prompt


def test_evidence_guard_allows_lint_recommendation_without_execution() -> None:
    changed_subgraph = ChangedSubgraph(
        changed_files=["app/main.py"],
        recommended_validation=[
            ImpactedValidation(
                command="uv run pytest tests/test_health.py -q",
                reason="related_tests_from_repo_graph",
            ),
            ImpactedValidation(
                command="uv run ruff check .",
                reason="style_validation_from_planner",
            ),
        ],
    )
    report = write_report(
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 0)]),
    )
    report.markdown = report.markdown.rstrip() + render_changed_subgraph_markdown(
        changed_subgraph
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[command("python -m pytest -q", 0)]),
        risk_report=sample_risk(),
        changed_subgraph=changed_subgraph,
    )

    assert evidence.grounded is True
    assert evidence.unsupported_claim_count == 0
