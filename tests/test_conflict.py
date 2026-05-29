from app.core.conflict import ConflictAuditor
from app.schemas.evidence import EvidenceReport
from app.schemas.permission import PermissionReport
from app.schemas.plan import ImplementationPlan
from app.schemas.report import FinalReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


def _passing_tests() -> TestRunSummary:
    return TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=0, duration_seconds=0.1)]
    )


def _failing_tests() -> TestRunSummary:
    return TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=1, duration_seconds=0.1)]
    )


def _audit(
    *,
    final_report: FinalReport | None = None,
    test_results: TestRunSummary | None = None,
    evidence: EvidenceReport | None = None,
    risk: RiskReport | None = None,
    permission: PermissionReport | None = None,
    plan: ImplementationPlan | None = None,
):
    return ConflictAuditor().audit(
        final_report=final_report or FinalReport(title="t", markdown="# body"),
        test_results=test_results or _passing_tests(),
        evidence_report=evidence or EvidenceReport(grounded=True),
        risk_report=risk or RiskReport(risk_score=5, risk_level="low", factors=[], blocked=False),
        permission_report=permission or PermissionReport(),
        plan=plan or ImplementationPlan(task="x", summary="s"),
    )


def test_consistent_run_has_no_conflicts():
    report = _audit()
    assert report.has_conflicts is False
    assert report.is_consistent is True


def test_report_claims_pass_while_tests_failed_is_critical():
    report = _audit(
        final_report=FinalReport(title="t", markdown="All tests pass and the build is green."),
        test_results=_failing_tests(),
    )
    codes = {c.code for c in report.conflicts}
    assert "claims_pass_but_tests_failed" in codes
    assert report.is_consistent is False


def test_ungrounded_evidence_is_a_conflict():
    report = _audit(evidence=EvidenceReport(grounded=False, unsupported_claim_count=3))
    codes = {c.code for c in report.conflicts}
    assert "ungrounded_report_claims" in codes


def test_blocked_gate_but_report_reads_ready_is_critical():
    blocked = RiskReport(
        risk_score=90, risk_level="critical", factors=["secret"], blocked=True
    )
    report = _audit(
        final_report=FinalReport(title="t", markdown="This change is ready to merge."),
        risk=blocked,
    )
    codes = {c.code for c in report.conflicts}
    assert "blocked_but_reads_ready" in codes
    assert report.is_consistent is False


def test_plan_requires_tests_but_none_ran_is_warning():
    plan = ImplementationPlan(task="x", summary="s", tests_to_run=["python -m pytest -q"])
    report = _audit(plan=plan, test_results=TestRunSummary(commands=[]))
    conflicts = {c.code: c for c in report.conflicts}
    assert "plan_requires_tests_but_none_ran" in conflicts
    assert conflicts["plan_requires_tests_but_none_ran"].severity == "warning"


def test_no_false_positive_when_report_is_honest_about_failure():
    # Report that honestly reports failure should not trigger the "claims pass" rule.
    report = _audit(
        final_report=FinalReport(title="t", markdown="Tests failed; needs fixes."),
        test_results=_failing_tests(),
    )
    codes = {c.code for c in report.conflicts}
    assert "claims_pass_but_tests_failed" not in codes
