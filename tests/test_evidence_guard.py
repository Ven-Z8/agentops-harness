from pathlib import Path

from app.agents.evidence_guard import EvidenceGuard
from app.core.graph import run_harness
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
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
