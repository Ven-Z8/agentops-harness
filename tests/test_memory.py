from app.core.memory import ExperienceMemory
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
from app.schemas.verification import VerificationBundle


def _record(
    *,
    run_id: str,
    task: str,
    tests: TestRunSummary | None = None,
    risk: RiskReport | None = None,
    status: str = "completed",
    bundle: VerificationBundle | None = None,
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
        verification_bundle=bundle or VerificationBundle(),
        status=status,
    )


def test_summary_distills_a_record():
    summary = ExperienceMemory().summarize(
        _record(run_id="a", task="Add logging middleware")
    )
    assert summary.run_id == "a"
    assert summary.tests_passed is True
    assert summary.is_implicit is False


def test_retrieve_ranks_lexically_similar_tasks_first():
    records = [
        _record(run_id="a", task="Add request logging middleware to the API"),
        _record(run_id="b", task="Refactor the database connection pool"),
        _record(run_id="c", task="Add structured logging to the service"),
    ]
    report = ExperienceMemory().retrieve("Add logging to the API", records, k=2)
    assert report.has_recall
    returned_ids = [e.episode.run_id for e in report.episodes]
    # The two logging-related tasks must outrank the database one.
    assert "b" not in returned_ids
    assert returned_ids[0] in {"a", "c"}


def test_retrieve_respects_k_limit():
    records = [
        _record(run_id=str(i), task=f"Add logging feature number {i}") for i in range(5)
    ]
    report = ExperienceMemory().retrieve("Add logging feature", records, k=3)
    assert len(report.episodes) == 3


def test_unrelated_task_yields_no_recall():
    records = [_record(run_id="a", task="Refactor database pooling")]
    report = ExperienceMemory().retrieve("Improve frontend button styling", records, k=3)
    assert report.has_recall is False
    assert report.episodes == []


def test_lesson_emitted_for_similar_implicit_episode():
    # A past logging task that completed with no tests = implicit convergence.
    past = _record(
        run_id="a",
        task="Add logging middleware",
        tests=TestRunSummary(commands=[]),
    )
    report = ExperienceMemory().retrieve("Add logging to the handler", [past], k=3)
    assert report.has_recall
    joined = " ".join(report.lessons).lower()
    assert "implicit" in joined or "verif" in joined


def test_lesson_emitted_for_similar_blocked_episode():
    blocked = _record(
        run_id="a",
        task="Edit the auth secret config",
        risk=RiskReport(risk_score=90, risk_level="critical", factors=["x"], blocked=True),
        status="blocked",
    )
    report = ExperienceMemory().retrieve("Edit the auth config file", [blocked], k=3)
    joined = " ".join(report.lessons).lower()
    assert "block" in joined or "approval" in joined or "security" in joined


def test_empty_history_is_safe():
    report = ExperienceMemory().retrieve("Any task", [], k=3)
    assert report.has_recall is False
    assert report.lessons == []
