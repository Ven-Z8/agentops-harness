"""Cross-artifact conflict auditor (Code-as-Agent-Harness §5.2.3).

Each harness artifact is produced by a different agent, so they can silently
disagree. This auditor compares them and surfaces contradictions the harness
would otherwise ship — e.g. a report that claims tests pass while the test
summary shows a failure, or a "ready to merge" report when a gate blocked the
change.

Detection is intentionally conservative: text matching on the report uses narrow
phrases so an *honest* report ("tests failed; needs fixes") is never flagged.
"""

from __future__ import annotations

import re

from app.schemas.conflict import Conflict, ConflictReport
from app.schemas.evidence import EvidenceReport
from app.schemas.permission import PermissionReport
from app.schemas.plan import ImplementationPlan
from app.schemas.report import FinalReport
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary

# Phrases that assert success. Matched as whole phrases so "tests failed" never
# trips "tests pass".
_PASS_CLAIM = re.compile(
    r"\b(all tests pass|tests pass|build is green|all green|everything passes)\b"
)
_READY_CLAIM = re.compile(
    r"\b(ready to merge|safe to merge|good to merge|ready for review|merge ready)\b"
)


class ConflictAuditor:
    def audit(
        self,
        *,
        final_report: FinalReport,
        test_results: TestRunSummary,
        evidence_report: EvidenceReport,
        risk_report: RiskReport,
        permission_report: PermissionReport,
        plan: ImplementationPlan,
    ) -> ConflictReport:
        text = final_report.markdown.lower()
        conflicts: list[Conflict] = []

        # 1. Report asserts success while tests actually failed.
        if _PASS_CLAIM.search(text) and not test_results.passed:
            conflicts.append(
                Conflict(
                    code="claims_pass_but_tests_failed",
                    severity="critical",
                    message=(
                        "The report claims tests pass, but the test summary shows a "
                        "failing command."
                    ),
                    sources=["final_report", "test_results"],
                )
            )

        # 2. Report claims are not grounded in the actual diff/tests.
        if not evidence_report.grounded or evidence_report.unsupported_claim_count > 0:
            conflicts.append(
                Conflict(
                    code="ungrounded_report_claims",
                    severity="warning",
                    message=(
                        "The evidence guard found report claims that are not supported "
                        "by the diff or test output."
                    ),
                    sources=["final_report", "evidence_report"],
                )
            )

        # 3. A security gate blocked the change, but the report reads as shippable.
        gate_blocked = risk_report.blocked or permission_report.blocked
        if gate_blocked and _READY_CLAIM.search(text):
            conflicts.append(
                Conflict(
                    code="blocked_but_reads_ready",
                    severity="critical",
                    message=(
                        "A security gate blocked this change, yet the report presents "
                        "it as ready to merge."
                    ),
                    sources=["final_report", "risk_report", "permission_report"],
                )
            )

        # 4. The plan asked for validation that never ran (implicit-convergence echo).
        if plan.tests_to_run and not test_results.commands:
            conflicts.append(
                Conflict(
                    code="plan_requires_tests_but_none_ran",
                    severity="warning",
                    message=(
                        "The plan listed validation commands, but no test command was "
                        "executed."
                    ),
                    sources=["plan", "test_results"],
                )
            )

        return ConflictReport(conflicts=conflicts)

    def append_to_report(
        self, final_report: FinalReport, report: ConflictReport
    ) -> FinalReport:
        """Append a human-readable conflict section to the report markdown."""
        if not report.has_conflicts:
            section = (
                "\n\n## Cross-Artifact Consistency (§5.2.3)\n\n"
                "No contradictions found across plan, tests, report, evidence, and gates."
            )
        else:
            lines = ["\n\n## Cross-Artifact Consistency (§5.2.3)\n"]
            for conflict in report.conflicts:
                lines.append(
                    f"- **[{conflict.severity}]** {conflict.message} "
                    f"(sources: {', '.join(conflict.sources)})"
                )
            section = "\n".join(lines)
        return final_report.model_copy(
            update={"markdown": final_report.markdown + section}
        )
