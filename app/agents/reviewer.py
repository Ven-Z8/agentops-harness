from app.core.llm import LLMClient
from app.schemas.review import ReviewFinding, ReviewReport
from app.schemas.test import TestRunSummary


class Reviewer:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    def review(self, changed_files: list[str], test_results: TestRunSummary) -> ReviewReport:
        if self.llm_client is not None:
            return self.llm_client.generate_structured(
                self._build_prompt(changed_files, test_results),
                ReviewReport,
            )

        findings: list[ReviewFinding] = []

        if not changed_files:
            findings.append(
                ReviewFinding(
                    severity="info",
                    title="No code changes detected",
                    description="The harness completed analysis without modifying the repository.",
                    recommendation=(
                        "Use this report as an implementation plan or rerun after applying a patch."
                    ),
                )
            )

        if not test_results.passed:
            findings.append(
                ReviewFinding(
                    severity="high",
                    title="Validation command failed",
                    description=(
                        "At least one configured test or lint command returned "
                        "a non-zero exit code."
                    ),
                    recommendation="Inspect command output and fix failures before opening a PR.",
                )
            )

        summary = "Review completed with no blocking findings."
        if findings:
            summary = f"Review completed with {len(findings)} finding(s)."

        return ReviewReport(findings=findings, summary=summary)

    def _build_prompt(self, changed_files: list[str], test_results: TestRunSummary) -> str:
        files = "\n".join(f"- {path}" for path in changed_files) or "- No files changed"
        commands = "\n".join(
            (
                f"- {result.command}: exit {result.exit_code}, "
                f"{result.duration_seconds:.3f}s\n"
                f"  stdout: {result.stdout[-1000:] or '<empty>'}\n"
                f"  stderr: {result.stderr[-1000:] or '<empty>'}"
            )
            for result in test_results.commands
        )
        return f"""You are the Reviewer Agent in AgentOps Harness.

Review the changed files and validation output. Return only data matching the ReviewReport schema.

Changed files:
{files}

Validation results:
{commands or "- No validation commands were run"}

Review rules:
- Prioritize correctness, missing tests, maintainability, and security.
- Do not invent files or changes that are not listed.
- If tests failed, include a high-severity finding.
- Keep recommendations actionable and PR-review style.
"""
