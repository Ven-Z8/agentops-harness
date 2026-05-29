from app.core.benchmark import ConvergenceClassifier, summarize_benchmark
from app.schemas.evidence import EvidenceReport
from app.schemas.permission import PermissionDecision, PermissionReport
from app.schemas.plan import ImplementationPlan
from app.schemas.quality import ReportQualityReport
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import CommandResult, TestRunSummary


def _record(
    *,
    run_id="r1",
    task="Add feature",
    tests: TestRunSummary | None = None,
    evidence: EvidenceReport | None = None,
    risk: RiskReport | None = None,
    permission: PermissionReport | None = None,
    quality: ReportQualityReport | None = None,
    status="completed",
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        task=task,
        repo_path="/tmp/repo",
        repo_profile=RepoProfile(repo_path="/tmp/repo"),
        plan=ImplementationPlan(task=task, summary="s"),
        test_results=tests
        or TestRunSummary(
            commands=[CommandResult(command="pytest", exit_code=0, duration_seconds=0.1)]
        ),
        review_report=ReviewReport(findings=[], summary="ok"),
        risk_report=risk or RiskReport(risk_score=5, risk_level="low", factors=[], blocked=False),
        permission_report=permission or PermissionReport(),
        final_report=FinalReport(title="t", markdown="# body"),
        report_quality=quality or ReportQualityReport(passed=True),
        evidence_report=evidence or EvidenceReport(grounded=True),
        status=status,
    )


def test_passing_run_reaches_correctness_and_is_not_implicit():
    profile = ConvergenceClassifier().classify(_record())
    assert "correctness" in profile.achieved
    assert profile.is_implicit is False


def test_run_without_tests_is_flagged_implicit():
    profile = ConvergenceClassifier().classify(
        _record(tests=TestRunSummary(commands=[]))
    )
    assert "correctness" not in profile.achieved
    assert profile.is_implicit is True
    assert any("implicit" in note.lower() for note in profile.notes)


def test_failed_tests_do_not_reach_correctness():
    failing = TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=1, duration_seconds=0.1)]
    )
    profile = ConvergenceClassifier().classify(_record(tests=failing))
    assert "correctness" not in profile.achieved


def test_unsupported_claims_block_correctness():
    profile = ConvergenceClassifier().classify(
        _record(evidence=EvidenceReport(grounded=False, unsupported_claim_count=2))
    )
    assert "correctness" not in profile.achieved


def test_security_convergence_when_no_gate_blocks():
    profile = ConvergenceClassifier().classify(_record())
    assert "security" in profile.achieved


def test_risk_block_removes_security_convergence():
    blocked_risk = RiskReport(
        risk_score=90, risk_level="critical", factors=["sensitive"], blocked=True
    )
    profile = ConvergenceClassifier().classify(
        _record(risk=blocked_risk, status="blocked")
    )
    assert "security" not in profile.achieved


def test_permission_deny_removes_security_convergence():
    denied = PermissionReport(
        decisions=[
            PermissionDecision(
                action="edit config/.env",
                tier="deny",
                rule="secret_file",
                reason="secret",
            )
        ]
    )
    profile = ConvergenceClassifier().classify(
        _record(permission=denied, status="blocked")
    )
    assert "security" not in profile.achieved


def test_blocked_run_is_not_implicit():
    # A run that correctly stopped on a security gate converged — it is not the
    # paper's implicit gap (which is *completing* without verification).
    blocked_risk = RiskReport(
        risk_score=90, risk_level="critical", factors=["x"], blocked=True
    )
    profile = ConvergenceClassifier().classify(
        _record(tests=TestRunSummary(commands=[]), risk=blocked_risk, status="blocked")
    )
    assert profile.is_implicit is False


def test_performance_and_consensus_are_never_reached():
    # The harness has no performance metric or multi-agent vote; these stay 0 —
    # an honest gap the benchmark must show, not hide.
    profile = ConvergenceClassifier().classify(_record())
    assert "performance" not in profile.achieved
    assert "consensus" not in profile.achieved


def test_summarize_aggregates_rates():
    classifier = ConvergenceClassifier()
    good = classifier.classify(_record(run_id="a"))
    implicit = classifier.classify(
        _record(run_id="b", tests=TestRunSummary(commands=[]))
    )
    report = summarize_benchmark([good, implicit])
    assert report.total == 2
    assert report.type_counts["correctness"] == 1
    assert report.implicit_count == 1
    assert report.implicit_rate == 0.5
    assert report.correctness_rate == 0.5


def test_render_markdown_argues_with_convergence_vocabulary():
    report = summarize_benchmark([ConvergenceClassifier().classify(_record())])
    md = ConvergenceClassifier().render_markdown(report)
    assert "Convergence" in md
    assert "implicit" in md.lower()
    assert "correctness" in md.lower()
