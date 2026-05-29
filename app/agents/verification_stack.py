"""Assembles the verification stack / evidence bundle (Code-as-Agent-Harness §5.2.2).

This agent runs no new checks. It consolidates the verifiers the harness already
executes — tests, code review, the risk guard, and the evidence guard — into a
single bundle in which each check declares its explicit scope (what it verifies,
what it cannot verify, its confidence), and surfaces the regions left untested
and the risks that remain.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceReport
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary
from app.schemas.verification import VerificationBundle, VerifierScope

_HIGH_SEVERITIES = {"high", "critical"}


class VerificationStack:
    def assemble(
        self,
        changed_files: list[str],
        test_results: TestRunSummary,
        review_report: ReviewReport,
        risk_report: RiskReport,
        evidence_report: EvidenceReport,
    ) -> VerificationBundle:
        checks = [
            self._tests_scope(test_results),
            self._review_scope(review_report),
            self._risk_scope(risk_report),
            self._evidence_scope(evidence_report),
        ]
        return VerificationBundle(
            checks=checks,
            untested_regions=self._untested_regions(changed_files, test_results),
            remaining_risks=self._remaining_risks(
                review_report, risk_report, evidence_report
            ),
        )

    # -- per-verifier scopes -------------------------------------------------

    def _tests_scope(self, test_results: TestRunSummary) -> VerifierScope:
        if not test_results.commands:
            verdict = "not_run"
            detail = "No validation commands were configured for this run."
        elif test_results.passed:
            verdict = "pass"
            detail = f"{len(test_results.commands)} command(s) exited 0."
        else:
            verdict = "fail"
            failed = [c.command for c in test_results.commands if c.exit_code != 0]
            detail = f"Failing command(s): {failed}"
        return VerifierScope(
            name="tests",
            verdict=verdict,
            confidence="high",
            verifies="Behavioral correctness for the code paths the test commands exercise.",
            cannot_verify=(
                "Untested code paths, semantic intent, security, and performance. "
                "A green suite is not the full specification."
            ),
            detail=detail,
        )

    def _review_scope(self, review_report: ReviewReport) -> VerifierScope:
        high = [f for f in review_report.findings if f.severity in _HIGH_SEVERITIES]
        if high:
            verdict = "fail"
        elif review_report.findings:
            verdict = "warn"
        else:
            verdict = "pass"
        return VerifierScope(
            name="code_review",
            verdict=verdict,
            confidence="medium",
            verifies="Code-quality and design issues detectable by reading the diff.",
            cannot_verify=(
                "Whether the change actually runs correctly; review is static "
                "judgement, not execution."
            ),
            detail=review_report.summary,
        )

    def _risk_scope(self, risk_report: RiskReport) -> VerifierScope:
        if risk_report.blocked:
            verdict = "fail"
        elif risk_report.risk_level == "low":
            verdict = "pass"
        else:  # medium, high, critical (not blocked) surface as a warning
            verdict = "warn"
        return VerifierScope(
            name="risk_guard",
            verdict=verdict,
            confidence="medium",
            verifies="Presence of high-risk change patterns (deletions, sensitive files).",
            cannot_verify=(
                "Whether a low-risk-looking change is actually correct or complete."
            ),
            detail=f"score={risk_report.risk_score} level={risk_report.risk_level}",
        )

    def _evidence_scope(self, evidence_report: EvidenceReport) -> VerifierScope:
        verdict = "pass" if evidence_report.grounded else "fail"
        return VerifierScope(
            name="evidence_guard",
            verdict=verdict,
            confidence="high",
            verifies="That report claims are grounded in the git and test record.",
            cannot_verify=(
                "Whether the underlying change is correct — only that the report "
                "does not overstate it."
            ),
            detail=f"unsupported_claims={evidence_report.unsupported_claim_count}",
        )

    # -- aggregates ----------------------------------------------------------

    def _untested_regions(
        self,
        changed_files: list[str],
        test_results: TestRunSummary,
    ) -> list[str]:
        regions: list[str] = []
        if not test_results.commands:
            regions.append(
                "No validation commands ran; the entire change is unverified by tests."
            )
        elif not test_results.passed:
            regions.append("Tests failed; passing behavior is not established.")

        has_changed_tests = any(path.startswith("tests/") for path in changed_files)
        if not has_changed_tests:
            for path in changed_files:
                if path.startswith("tests/"):
                    continue
                regions.append(f"{path} changed but no test file was added or updated.")
        return regions

    def _remaining_risks(
        self,
        review_report: ReviewReport,
        risk_report: RiskReport,
        evidence_report: EvidenceReport,
    ) -> list[str]:
        risks: list[str] = []
        # The risk guard emits a benign sentinel when nothing is wrong; that is the
        # absence of a risk, not a remaining one.
        risks.extend(
            factor
            for factor in risk_report.factors
            if "no material risk" not in factor.lower()
        )
        for finding in review_report.findings:
            if finding.severity in _HIGH_SEVERITIES:
                risks.append(f"{finding.severity}: {finding.title}")
        for finding in evidence_report.findings:
            risks.append(f"unsupported claim: {finding.claim}")
        return risks

    # -- rendering -----------------------------------------------------------

    def append_to_report(
        self,
        final_report: FinalReport,
        bundle: VerificationBundle,
    ) -> FinalReport:
        lines = [
            final_report.markdown.rstrip(),
            "",
            "## Verification Stack",
            "",
            f"**Accepted:** {bundle.accepted} · "
            f"**Overall confidence:** {bundle.overall_confidence}",
            "",
            "| Check | Verdict | Confidence | Verifies | Cannot verify |",
            "|---|---|---|---|---|",
        ]
        for check in bundle.checks:
            lines.append(
                f"| {check.name} | {check.verdict} | {check.confidence} | "
                f"{check.verifies} | {check.cannot_verify} |"
            )

        if bundle.untested_regions:
            lines.append("")
            lines.append("**Untested regions:**")
            lines.extend(f"- {region}" for region in bundle.untested_regions)

        if bundle.remaining_risks:
            lines.append("")
            lines.append("**Remaining risks:**")
            lines.extend(f"- {risk}" for risk in bundle.remaining_risks)

        lines.append("")
        return FinalReport(
            title=final_report.title,
            markdown="\n".join(lines),
        )
