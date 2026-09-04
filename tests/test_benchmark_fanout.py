"""Benchmark fan-out tests (AO-P2-01): one spec × many workers → comparison.

Hermetic by construction: dispatch is injected, so the comparison logic is
tested against deterministic records — the fan-out never fabricates a run.
"""

from __future__ import annotations

import pytest

from app.core.benchmark_fanout import BenchmarkFanout, render_fanout_markdown
from app.schemas.benchmark import FanoutReport
from app.schemas.evidence import EvidenceReport
from app.schemas.permission import PermissionReport
from app.schemas.plan import ImplementationPlan
from app.schemas.quality import ReportQualityReport
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.task_spec import SweTaskSpec
from app.schemas.test import CommandResult, TestRunSummary

BASE = "b86d1d7d72f55ef6a4424069bfebdb608e248153"


def _spec() -> SweTaskSpec:
    return SweTaskSpec(
        repo="example/widgetlib",
        base_commit=BASE,
        problem_statement="reset(keep_name=True) drops the name",
        fail_to_pass=["tests/test_widget.py::test_keep_name"],
        pass_to_pass=[],
    )


def _record(
    *,
    run_id: str,
    tests_passed: bool = True,
    grounded: bool = True,
    status: str = "completed",
) -> RunRecord:
    exit_code = 0 if tests_passed else 1
    return RunRecord(
        run_id=run_id,
        task="reset(keep_name=True) drops the name",
        repo_path="/tmp/repo",
        repo_profile=RepoProfile(repo_path="/tmp/repo"),
        plan=ImplementationPlan(task="t", summary="s"),
        test_results=TestRunSummary(
            commands=[CommandResult(command="pytest", exit_code=exit_code, duration_seconds=0.1)]
        ),
        review_report=ReviewReport(findings=[], summary="ok"),
        risk_report=RiskReport(risk_score=5, risk_level="low", factors=[], blocked=False),
        permission_report=PermissionReport(),
        final_report=FinalReport(title="t", markdown="# body"),
        report_quality=ReportQualityReport(passed=True),
        evidence_report=EvidenceReport(grounded=grounded),
        status=status,
    )


class TestFanoutComparison:
    def test_compare_attaches_profile_per_arm(self) -> None:
        report = BenchmarkFanout().compare(
            _spec(),
            [
                ("openhands", _record(run_id="run-a")),
                ("codex", _record(run_id="run-b", tests_passed=False)),
            ],
        )

        assert report.repo == "example/widgetlib"
        assert report.base_commit == BASE
        assert [arm.worker for arm in report.arms] == ["openhands", "codex"]
        assert report.arms[0].run_id == "run-a"
        assert "correctness" in report.arms[0].profile.achieved
        assert "correctness" not in report.arms[1].profile.achieved

    def test_correctness_and_implicit_rates(self) -> None:
        report = BenchmarkFanout().compare(
            _spec(),
            [
                ("w1", _record(run_id="a")),
                ("w2", _record(run_id="b", tests_passed=False)),  # implicit: done, unverified
                ("w3", _record(run_id="c")),
            ],
        )

        assert report.total == 3
        assert report.correctness_count == 2
        assert report.implicit_count == 1
        assert report.correctness_rate == pytest.approx(2 / 3)
        assert report.implicit_rate == pytest.approx(1 / 3)
        assert report.workers_reaching_correctness == ["w1", "w3"]
        assert report.implicit_workers == ["w2"]

    def test_agreement_true_when_all_reach_correctness(self) -> None:
        report = BenchmarkFanout().compare(
            _spec(), [("a", _record(run_id="a")), ("b", _record(run_id="b"))]
        )
        assert report.agreement is True

    def test_agreement_true_when_none_reaches_correctness(self) -> None:
        report = BenchmarkFanout().compare(
            _spec(),
            [
                ("a", _record(run_id="a", tests_passed=False)),
                ("b", _record(run_id="b", tests_passed=False)),
            ],
        )
        assert report.agreement is True
        assert report.correctness_count == 0

    def test_agreement_false_on_mixed_outcome(self) -> None:
        """Mixed = the signal the fan-out exists to surface."""
        report = BenchmarkFanout().compare(
            _spec(),
            [("a", _record(run_id="a")), ("b", _record(run_id="b", tests_passed=False))],
        )
        assert report.agreement is False

    def test_failed_status_is_not_implicit(self) -> None:
        """A run that failed its contract is honest failure, not the gap."""
        report = BenchmarkFanout().compare(
            _spec(),
            [("a", _record(run_id="a", tests_passed=False, status="failed"))],
        )
        assert report.implicit_count == 0
        assert report.arms[0].status == "failed"


class TestFanoutDispatch:
    def test_run_dispatches_every_arm_once_in_order(self) -> None:
        calls: list[str] = []

        def dispatch(worker: str) -> RunRecord:
            calls.append(worker)
            return _record(run_id=f"run-{worker}")

        report = BenchmarkFanout().run(_spec(), ["openhands", "codex", "claude"], dispatch)

        assert calls == ["openhands", "codex", "claude"]
        assert [arm.worker for arm in report.arms] == calls

    def test_run_requires_at_least_one_arm(self) -> None:
        with pytest.raises(ValueError, match="at least one worker"):
            BenchmarkFanout().run(_spec(), [], lambda worker: _record(run_id="x"))


class TestFanoutRendering:
    def test_render_surfaces_mixed_verdict_and_implicit_arms(self) -> None:
        report = BenchmarkFanout().compare(
            _spec(),
            [
                ("openhands", _record(run_id="run-a")),
                ("codex", _record(run_id="run-b", tests_passed=False)),
            ],
        )

        markdown = render_fanout_markdown(report)

        assert "example/widgetlib" in markdown
        assert "MIXED outcome" in markdown
        assert "| openhands |" in markdown
        assert "| codex |" in markdown
        assert "codex" in markdown.split("Implicit arms")[1]

    def test_render_empty_report_has_no_rates_or_verdict(self) -> None:
        report = FanoutReport(repo="example/widgetlib", base_commit=BASE)
        markdown = render_fanout_markdown(report)
        assert "Arms:** 0" in markdown
        assert "Agreement" not in markdown
