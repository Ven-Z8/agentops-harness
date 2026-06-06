from app.core.llm import LLMClient
from app.prompts.pr_writer import build_pr_writer_prompt, format_edit_summary
from app.schemas.edit import ExternalEditResult
from app.schemas.plan import ImplementationPlan
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary


class PRWriter:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    def write(
        self,
        task: str,
        plan: ImplementationPlan,
        changed_files: list[str],
        test_results: TestRunSummary,
        review_report: ReviewReport,
        risk_report: RiskReport,
        edit_result: ExternalEditResult | None = None,
    ) -> FinalReport:
        if self.llm_client is not None:
            markdown = self.llm_client.generate_text(
                self._build_prompt(
                    task=task,
                    plan=plan,
                    changed_files=changed_files,
                    test_results=test_results,
                    review_report=review_report,
                    risk_report=risk_report,
                    edit_result=edit_result,
                )
            )
            return FinalReport(title="AgentOps Harness Report", markdown=markdown)

        files = "\n".join(f"- `{path}`" for path in changed_files) or "- No files changed"
        edit_summary = self._format_edit_summary(edit_result)
        tests = "\n".join(
            f"- `{result.command}`: exit {result.exit_code} in {result.duration_seconds:.3f}s"
            for result in test_results.commands
        )
        findings = "\n".join(
            f"- **{finding.severity.upper()}** {finding.title}: {finding.recommendation}"
            for finding in review_report.findings
        ) or "- No review findings"
        risk_factors = "\n".join(f"- {factor}" for factor in risk_report.factors)

        markdown = f"""# AgentOps Harness Report

## Summary
{task}

## What changed
{plan.summary}

{edit_summary}

## Files changed
{files}

## Tests run
{tests}

## Risk assessment
- Score: {risk_report.risk_score}/100
- Level: {risk_report.risk_level}
- Blocked: {risk_report.blocked}

{risk_factors}

## Reviewer notes
{findings}

## Follow-up tasks
- Apply the implementation plan if this was an analysis-only run.
- Re-run the harness after code changes to compare risk and validation results.
"""
        return FinalReport(title="AgentOps Harness Report", markdown=markdown)

    def _build_prompt(
        self,
        task: str,
        plan: ImplementationPlan,
        changed_files: list[str],
        test_results: TestRunSummary,
        review_report: ReviewReport,
        risk_report: RiskReport,
        edit_result: ExternalEditResult | None = None,
    ) -> str:
        return build_pr_writer_prompt(
            task=task,
            plan=plan,
            changed_files=changed_files,
            test_results=test_results,
            review_report=review_report,
            risk_report=risk_report,
            edit_result=edit_result,
        )

    def _format_edit_summary(self, edit_result: ExternalEditResult | None) -> str:
        return format_edit_summary(edit_result)
