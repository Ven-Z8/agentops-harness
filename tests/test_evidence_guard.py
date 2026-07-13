from pathlib import Path

import pytest

from app.agents.evidence_guard import EvidenceGuard
from app.core.graph import run_harness
from app.core.repo_graph.impact import ChangedSubgraph, ImpactedRoute, ImpactedValidation
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


class HallucinatingReportLLM:
    def generate_text(self, prompt: str) -> str:
        return """# PR Report

## Summary
This report claims implementation happened.

## What changed
- Added `app/middleware/request_logging.py`
- Added `tests/test_request_logging.py`

## Files changed
- `app/middleware/request_logging.py`
- `tests/test_request_logging.py`

## Tests run
All tests pass and new tests were added.

## Risk assessment
- Score: 0/100

## Reviewer notes
- No findings.

## Follow-up tasks
- Wire middleware into the app.
"""

    def generate_structured(self, prompt: str, schema: type) -> object:
        if schema is ImplementationPlan:
            return ImplementationPlan(
                task="Add request logging middleware with tests",
                summary="Plan request logging middleware.",
                steps=[
                    PlanStep(
                        id=1,
                        title="Plan middleware",
                        description="Plan request logging middleware and tests.",
                    )
                ],
                acceptance_criteria=["Request logging behavior is covered."],
                tests_to_run=["python -m pytest -q"],
            )
        if schema is ReviewReport:
            return ReviewReport(summary="No review findings.", findings=[])
        raise AssertionError(f"Unexpected schema: {schema}")


def passing_tests() -> TestRunSummary:
    return TestRunSummary(
        commands=[
            CommandResult(
                command="python -m pytest -q",
                exit_code=0,
                duration_seconds=0.1,
                stdout="1 passed",
                stderr="",
            )
        ]
    )


def test_evidence_guard_flags_unsupported_file_claims() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="- Added `app/middleware/request_logging.py`\n- All tests pass.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=[],
        test_results=passing_tests(),
    )

    assert evidence.grounded is False
    assert evidence.unsupported_claim_count == 1
    assert evidence.findings[0].claim == "app/middleware/request_logging.py"
    assert evidence.findings[0].claim_type == "file_changed_without_diff"
    assert evidence.findings[0].source_of_truth == "changed_files"
    assert evidence.findings[0].citation == "RunRecord.changed_files"


def test_evidence_guard_flags_new_tests_claim_without_test_file_changes() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="Comprehensive tests were added for request logging.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is False
    assert any("tests" in finding.claim.lower() for finding in evidence.findings)


def test_evidence_guard_flags_updated_test_claim_without_test_file_changes() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="All existing tests pass, including the updated health endpoint test.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is False
    assert any(
        finding.claim_type == "tests_added_without_test_diff"
        for finding in evidence.findings
    )


@pytest.mark.parametrize(
    "claim",
    [
        "No tests were modified; all existing tests continue to pass.",
        "No additional new tests were added; the focused suite still passes.",
    ],
)
def test_evidence_guard_accepts_explicit_no_test_changes_statement(claim: str) -> None:
    report = FinalReport(
        title="PR Report",
        markdown=claim,
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/models.py", "app/service.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is True
    assert evidence.unsupported_claim_count == 0


@pytest.mark.parametrize(
    "claim",
    [
        "We changed the implementation and ran tests to verify the new route.",
        "We modified app code and used tests for validation.",
        "Changed app behavior and ran the focused tests to confirm.",
    ],
)
def test_evidence_guard_accepts_validation_mentions_after_app_changes(claim: str) -> None:
    evidence = EvidenceGuard().check(
        final_report=FinalReport(title="PR Report", markdown=claim),
        changed_files=["app/main.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is True
    assert evidence.unsupported_claim_count == 0


@pytest.mark.parametrize(
    "claim",
    [
        "We updated unit and integration tests.",
        "The change modified all four relevant unit tests.",
        "We updated unit and integration tests for the new route.",
        "The change modified all four relevant unit tests to cover the migration.",
        "We changed the endpoint tests so they exercise the new response.",
    ],
)
def test_evidence_guard_flags_positive_test_update_claims(claim: str) -> None:
    evidence = EvidenceGuard().check(
        final_report=FinalReport(title="PR Report", markdown=claim),
        changed_files=["app/models.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is False
    assert any(
        finding.claim_type == "tests_added_without_test_diff"
        for finding in evidence.findings
    )


def test_evidence_guard_flags_lint_claim_without_lint_command() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="Linting: ruff completed with no errors.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is False
    finding = evidence.findings[0]
    assert finding.claim_type == "lint_claim_without_execution"
    assert finding.source_of_truth == "test_results.commands"


def test_evidence_guard_does_not_treat_external_worker_command_as_changed_file() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="The external worker executed the change (`worker.py`) successfully.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
    )

    assert evidence.grounded is True


def test_evidence_guard_flags_route_claim_without_changed_subgraph_evidence() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="Changed GET /admin behavior.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
        changed_subgraph=ChangedSubgraph(
            changed_files=["app/main.py"],
            impacted_routes=[
                ImpactedRoute(
                    method="GET",
                    path="/health",
                    source_file="app/main.py",
                    node_id="route:python:GET:/health",
                )
            ],
        ),
    )

    assert evidence.grounded is False
    finding = evidence.findings[0]
    assert finding.claim == "GET /admin"
    assert finding.claim_type == "route_claim_without_graph_impact"
    assert finding.source_of_truth == "changed_subgraph.impacted_routes"


def test_evidence_guard_flags_low_risk_claim_when_risk_is_high() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="This is low risk and safe.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=[".env"],
        test_results=passing_tests(),
        risk_report=RiskReport(risk_score=90, risk_level="high", factors=["Sensitive file"]),
    )

    assert evidence.grounded is False
    finding = evidence.findings[0]
    assert finding.claim_type == "risk_level_understated"
    assert finding.source_of_truth == "risk_report"


def test_evidence_guard_distinguishes_recommended_from_executed_validation() -> None:
    report = FinalReport(
        title="PR Report",
        markdown="Tests run: uv run pytest tests/test_health.py -q",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=["app/main.py"],
        test_results=passing_tests(),
        changed_subgraph=ChangedSubgraph(
            changed_files=["app/main.py"],
            recommended_validation=[
                ImpactedValidation(
                    command="uv run pytest tests/test_health.py -q",
                    reason="related_tests_from_repo_graph",
                )
            ],
        ),
    )

    assert evidence.grounded is False
    finding = evidence.findings[0]
    assert finding.claim_type == "recommended_validation_claimed_as_executed"
    assert finding.source_of_truth == "test_results.commands"


def test_evidence_guard_passes_analysis_only_report() -> None:
    report = FinalReport(
        title="AgentOps Harness Report",
        markdown="This was an analysis-only run. No files changed.",
    )

    evidence = EvidenceGuard().check(
        final_report=report,
        changed_files=[],
        test_results=passing_tests(),
    )

    assert evidence.grounded is True
    assert evidence.unsupported_claim_count == 0


def test_run_harness_appends_evidence_guard_findings(tmp_path: Path) -> None:
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware with tests",
        storage_path=tmp_path / "runs.db",
        llm_client=HallucinatingReportLLM(),
    )

    assert record.evidence_report.grounded is False
    assert "Evidence Guard" in record.final_report.markdown
    assert "Unsupported claim" in record.final_report.markdown
