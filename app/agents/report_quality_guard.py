from __future__ import annotations

from app.schemas.quality import ReportQualityFinding, ReportQualityReport
from app.schemas.report import FinalReport


class ReportQualityGuard:
    REQUIRED_SECTIONS = (
        "summary",
        "what changed",
        "files changed",
        "tests run",
        "risk assessment",
        "reviewer notes",
        "follow-up tasks",
    )
    ARTIFACT_MARKERS = ("<｜image｜>", "<｜place", "▁holder", "Here<")

    def check(self, final_report: FinalReport) -> ReportQualityReport:
        findings: list[ReportQualityFinding] = []
        markdown = final_report.markdown
        lowered = markdown.lower()

        if len(markdown.strip()) < 120:
            findings.append(
                ReportQualityFinding(
                    severity="error",
                    reason="report is too short to be a useful PR summary",
                    evidence=f"length={len(markdown.strip())}",
                )
            )

        if any(marker in markdown for marker in self.ARTIFACT_MARKERS):
            findings.append(
                ReportQualityFinding(
                    severity="error",
                    reason="report contains placeholder/image artifacts",
                    evidence="artifact marker detected",
                )
            )

        missing_sections = [
            section
            for section in self.REQUIRED_SECTIONS
            if f"## {section}" not in lowered and f"### {section}" not in lowered
        ]
        if missing_sections:
            findings.append(
                ReportQualityFinding(
                    severity="error",
                    reason="report is missing required PR sections",
                    evidence=", ".join(missing_sections),
                )
            )

        return ReportQualityReport(passed=not findings, findings=findings)

    def mark_fallback(self, report: ReportQualityReport) -> ReportQualityReport:
        return report.model_copy(update={"fallback_used": True})

    def append_to_report(
        self,
        final_report: FinalReport,
        quality_report: ReportQualityReport,
    ) -> FinalReport:
        if quality_report.passed and not quality_report.fallback_used:
            return final_report

        findings = "\n".join(
            f"- **{finding.severity.upper()}** {finding.reason}. Evidence: {finding.evidence}"
            for finding in quality_report.findings
        )
        if not findings:
            findings = "- Original provider report passed quality checks."

        fallback_line = (
            "- Fallback deterministic report was used."
            if quality_report.fallback_used
            else "- Provider report was used."
        )
        markdown = f"""{final_report.markdown.rstrip()}

## Report Quality Guard

{fallback_line}

{findings}
"""
        return FinalReport(title=final_report.title, markdown=markdown)
