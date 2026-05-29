from app.core.evolution import EvolutionAgent
from app.schemas.evidence import EvidenceReport
from app.schemas.permission import PermissionReport
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
    run_id: str,
    task: str = "Add feature",
    tests: TestRunSummary | None = None,
    risk: RiskReport | None = None,
    status: str = "completed",
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
        permission_report=PermissionReport(),
        final_report=FinalReport(title="t", markdown="# body"),
        report_quality=ReportQualityReport(passed=True),
        evidence_report=EvidenceReport(grounded=True),
        status=status,
    )


def _no_tests() -> TestRunSummary:
    return TestRunSummary(commands=[])


def _failing() -> TestRunSummary:
    return TestRunSummary(
        commands=[CommandResult(command="pytest", exit_code=1, duration_seconds=0.1)]
    )


def _blocked_risk() -> RiskReport:
    return RiskReport(risk_score=90, risk_level="critical", factors=["x"], blocked=True)


def test_empty_history_yields_no_proposals():
    report = EvolutionAgent().analyze([])
    assert report.runs_analyzed == 0
    assert report.has_proposals is False


def test_healthy_history_yields_no_proposals():
    records = [_record(run_id=str(i)) for i in range(4)]
    report = EvolutionAgent().analyze(records)
    assert report.runs_analyzed == 4
    assert report.has_proposals is False


def test_high_implicit_rate_proposes_enforcing_validation():
    # 3 of 4 runs completed with no validation -> implicit convergence dominates.
    records = [_record(run_id=str(i), tests=_no_tests()) for i in range(3)]
    records.append(_record(run_id="ok"))
    report = EvolutionAgent().analyze(records)
    codes = {p.code: p for p in report.proposals}
    assert "enforce_validation_commands" in codes
    assert codes["enforce_validation_commands"].priority == "high"
    # The proposal must cite the offending runs as evidence.
    assert set(codes["enforce_validation_commands"].evidence_run_ids) == {"0", "1", "2"}


def test_repeated_failures_proposes_investigation():
    records = [
        _record(run_id="a", tests=_failing()),
        _record(run_id="b", tests=_failing()),
        _record(run_id="c"),
    ]
    report = EvolutionAgent().analyze(records)
    codes = {p.code for p in report.proposals}
    assert "investigate_recurring_test_failures" in codes


def test_clustered_blocks_proposes_policy():
    records = [
        _record(run_id="a", risk=_blocked_risk(), status="blocked"),
        _record(run_id="b", risk=_blocked_risk(), status="blocked"),
        _record(run_id="c"),
    ]
    report = EvolutionAgent().analyze(records)
    codes = {p.code for p in report.proposals}
    assert "codify_recurring_security_blocks" in codes


def test_render_markdown_lists_proposals():
    records = [_record(run_id=str(i), tests=_no_tests()) for i in range(3)]
    report = EvolutionAgent().analyze(records)
    md = EvolutionAgent().render_markdown(report)
    assert "Evolution" in md
    assert "enforce_validation_commands" in md
