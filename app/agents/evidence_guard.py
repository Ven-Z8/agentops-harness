from __future__ import annotations

import re

from app.schemas.evidence import EvidenceFinding, EvidenceReport
from app.schemas.report import FinalReport
from app.schemas.test import TestRunSummary


class EvidenceGuard:
    FILE_CLAIM_PATTERN = re.compile(r"`([^`]+\.[A-Za-z0-9_]+)`")
    CHANGE_WORDS = (
        "add",
        "added",
        "adds",
        "modify",
        "modified",
        "change",
        "changed",
        "create",
        "created",
        "implement",
        "implemented",
    )
    TEST_CLAIM_PATTERNS = (
        "tests were added",
        "test was added",
        "added tests",
        "new tests",
        "comprehensive tests",
    )

    def check(
        self,
        final_report: FinalReport,
        changed_files: list[str],
        test_results: TestRunSummary,
    ) -> EvidenceReport:
        markdown = final_report.markdown
        findings: list[EvidenceFinding] = []
        changed_file_set = set(changed_files)

        findings.extend(self._check_file_claims(markdown, changed_file_set))
        findings.extend(self._check_new_test_claims(markdown, changed_file_set))
        findings.extend(self._check_analysis_only(markdown, changed_files))
        findings.extend(self._check_test_pass_claims(markdown, test_results))

        return EvidenceReport(
            grounded=not findings,
            unsupported_claim_count=len(findings),
            findings=findings,
        )

    def append_to_report(
        self,
        final_report: FinalReport,
        evidence_report: EvidenceReport,
    ) -> FinalReport:
        if evidence_report.grounded:
            return final_report

        findings = "\n".join(
            (
                f"- **Unsupported claim** `{finding.claim}`: "
                f"{finding.reason} Evidence: {finding.evidence}"
            )
            for finding in evidence_report.findings
        )
        markdown = f"""{final_report.markdown.rstrip()}

## Evidence Guard

This report contains claims that are not supported by the run record.

{findings}
"""
        return FinalReport(title=final_report.title, markdown=markdown)

    def _check_file_claims(
        self,
        markdown: str,
        changed_file_set: set[str],
    ) -> list[EvidenceFinding]:
        findings: list[EvidenceFinding] = []
        for line in markdown.splitlines():
            if not self._looks_like_change_claim(line):
                continue
            for file_path in self.FILE_CLAIM_PATTERN.findall(line):
                if file_path not in changed_file_set:
                    findings.append(
                        EvidenceFinding(
                            severity="error",
                            claim=file_path,
                            reason=(
                                "Report claims a file was changed, but git evidence "
                                "does not include it."
                            ),
                            evidence=f"changed_files={sorted(changed_file_set)}",
                        )
                    )
        return findings

    def _check_new_test_claims(
        self,
        markdown: str,
        changed_file_set: set[str],
    ) -> list[EvidenceFinding]:
        lowered = markdown.lower()
        has_test_claim = any(pattern in lowered for pattern in self.TEST_CLAIM_PATTERNS)
        has_changed_tests = any(path.startswith("tests/") for path in changed_file_set)
        if has_test_claim and not has_changed_tests:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="new tests added",
                    reason="Report claims tests were added, but no changed test file is present.",
                    evidence=f"changed_files={sorted(changed_file_set)}",
                )
            ]
        return []

    def _check_analysis_only(
        self,
        markdown: str,
        changed_files: list[str],
    ) -> list[EvidenceFinding]:
        lowered = markdown.lower()
        if changed_files:
            return []
        if any(word in lowered for word in ("added `", "modified `", "created `")):
            return []
        if "analysis-only" in lowered or "no files changed" in lowered:
            return []
        return [
            EvidenceFinding(
                severity="warning",
                claim="implementation report without changed files",
                reason=(
                    "Run has no changed files, so report should clearly state "
                    "it is analysis-only."
                ),
                evidence="changed_files=[]",
            )
        ]

    def _check_test_pass_claims(
        self,
        markdown: str,
        test_results: TestRunSummary,
    ) -> list[EvidenceFinding]:
        lowered = markdown.lower()
        claims_pass = "all tests pass" in lowered or "tests pass" in lowered
        if claims_pass and not test_results.passed:
            return [
                EvidenceFinding(
                    severity="error",
                    claim="tests pass",
                    reason="Report claims tests pass, but validation commands failed.",
                    evidence="test_results.passed=False",
                )
            ]
        return []

    def _looks_like_change_claim(self, line: str) -> bool:
        lowered = line.lower()
        return any(word in lowered for word in self.CHANGE_WORDS)
