from __future__ import annotations

from app.schemas.edit import ExternalEditResult
from app.schemas.plan import ImplementationPlan
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary


def build_pr_writer_prompt(
    *,
    task: str,
    plan: ImplementationPlan,
    changed_files: list[str],
    test_results: TestRunSummary,
    review_report: ReviewReport,
    risk_report: RiskReport,
    edit_result: ExternalEditResult | None = None,
) -> str:
    files = "\n".join(f"- {path}" for path in changed_files) or "- No files changed"
    tests = "\n".join(
        f"- {result.command}: exit {result.exit_code} in {result.duration_seconds:.3f}s"
        for result in test_results.commands
    )
    findings = "\n".join(
        f"- {finding.severity}: {finding.title} - {finding.recommendation}"
        for finding in review_report.findings
    ) or "- No review findings"
    risk_factors = "\n".join(f"- {factor}" for factor in risk_report.factors)
    acceptance = "\n".join(f"- {item}" for item in plan.acceptance_criteria)

    return f"""You are the PR Writer Agent in AgentOps Harness.

Write a professional GitHub-style PR report in Markdown.

Required sections:
- Summary
- What changed
- Files changed
- Tests run
- Risk assessment
- Reviewer notes
- Follow-up tasks

Task:
{task}

Plan summary:
{plan.summary}

Acceptance criteria:
{acceptance or "- None"}

Changed files:
{files}

Tests:
{tests or "- No validation commands were run"}

Risk:
- Score: {risk_report.risk_score}/100
- Level: {risk_report.risk_level}
- Blocked: {risk_report.blocked}

Risk factors:
{risk_factors}

Review findings:
{findings}

External edit result:
{format_edit_summary(edit_result)}
"""


def format_edit_summary(edit_result: ExternalEditResult | None) -> str:
    if edit_result is None:
        return "## Edit mode\n- Mode: observe-only"

    return f"""## Edit mode
- Mode: external worker
- Status: {edit_result.status}
- Command: `{edit_result.command}`
- Exit code: {edit_result.exit_code}
- Duration: {edit_result.duration_seconds:.3f}s"""
