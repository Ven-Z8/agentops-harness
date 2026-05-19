from pathlib import Path

from app.agents.report_quality_guard import ReportQualityGuard
from app.core.graph import run_harness
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport


class GarbledReportLLM:
    def generate_text(self, prompt: str) -> str:
        return "Here<｜image｜><｜image｜>购销图谱96704975Val975975975"

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


def test_report_quality_guard_rejects_garbled_output() -> None:
    quality = ReportQualityGuard().check(
        FinalReport(
            title="AgentOps Harness Report",
            markdown="Here<｜image｜><｜image｜>购销图谱96704975Val975975975",
        )
    )

    assert quality.passed is False
    assert quality.fallback_used is False
    assert any("placeholder/image artifacts" in finding.reason for finding in quality.findings)


def test_report_quality_guard_accepts_required_sections() -> None:
    quality = ReportQualityGuard().check(
        FinalReport(
            title="AgentOps Harness Report",
            markdown="""# AgentOps Harness Report

## Summary
Analysis-only run.

## What changed
No files changed.

## Files changed
- No files changed

## Tests run
- `python -m pytest -q`: exit 0

## Risk assessment
- Score: 0/100

## Reviewer notes
- No findings

## Follow-up tasks
- Apply the plan.
""",
        )
    )

    assert quality.passed is True
    assert quality.findings == []


def test_run_harness_falls_back_when_llm_report_is_garbled(tmp_path: Path) -> None:
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware with tests",
        storage_path=tmp_path / "runs.db",
        llm_client=GarbledReportLLM(),
    )

    assert record.report_quality.passed is False
    assert record.report_quality.fallback_used is True
    assert "Report Quality Guard" in record.final_report.markdown
    assert "Here<" not in record.final_report.markdown
    assert "Risk assessment" in record.final_report.markdown
