from datetime import UTC, datetime

from app.core.repo_graph.models import RepoGraph
from app.schemas.memory import MemoryReport
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import TestRunSummary


def minimal_run_record() -> RunRecord:
    return RunRecord(
        run_id="testrun",
        task="t",
        repo_path=".",
        repo_profile=RepoProfile(repo_path="."),
        repo_graph=RepoGraph(repo_path="."),
        memory_report=MemoryReport(),
        plan=ImplementationPlan(
            task="t",
            summary="s",
            steps=[PlanStep(id=1, title="a", description="d")],
            acceptance_criteria=["ok"],
            tests_to_run=["python -m pytest -q"],
        ),
        test_results=TestRunSummary(commands=[]),
        review_report=ReviewReport(summary="s", findings=[]),
        risk_report=RiskReport(risk_score=0, risk_level="low", factors=[]),
        final_report=FinalReport(title="t", markdown="# t"),
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
