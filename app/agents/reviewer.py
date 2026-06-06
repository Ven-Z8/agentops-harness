from app.core.llm import LLMClient
from app.prompts.reviewer import build_reviewer_prompt
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
        return build_reviewer_prompt(
            changed_files=changed_files,
            test_results=test_results,
        )
