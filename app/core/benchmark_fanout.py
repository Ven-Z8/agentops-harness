"""Benchmark fan-out: one task-spec × many workers → convergence comparison.

Phase-2 benchmark entry (AO-P2-01). The convergence classifier in
``app.core.benchmark`` already types a SINGLE run; the fan-out runs the same
pinned spec across multiple workers and compares HOW EACH ONE converged.

Why this shape:

- A raw benchmark ("worker A: 0.3 s, tests 1/1") argues nothing about
  reliability. A convergence-typed fan-out argues something: it shows which
  workers reached real correctness convergence and which stopped implicitly
  (finished without a verification signal) on the SAME pinned contract.
- Dispatch is injected (``dispatch(worker) -> RunRecord``): production wires
  the governed spec pipeline per arm; tests inject deterministic records, so
  the comparison logic is hermetic. The fan-out itself never fabricates a
  record — it only classifies what a real run produced.
- Fail-closed honesty is inherited: each arm's status is whatever the
  governed pipeline recorded (a positive-contract violation already folds to
  ``failed`` upstream), and the report surfaces implicit arms rather than
  averaging them away.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.core.benchmark import ConvergenceClassifier
from app.schemas.benchmark import FanoutArm, FanoutReport
from app.schemas.run import RunRecord
from app.schemas.task_spec import SweTaskSpec

ArmDispatcher = Callable[[str], RunRecord]


class BenchmarkFanout:
    """Classify and compare one run per worker arm against a shared spec."""

    def __init__(self, classifier: ConvergenceClassifier | None = None) -> None:
        self._classifier = classifier or ConvergenceClassifier()

    def compare(
        self,
        spec: SweTaskSpec,
        arms: Iterable[tuple[str, RunRecord]],
    ) -> FanoutReport:
        """Build the comparison from (worker, record) pairs.

        Each record must come from a real governed run of ``spec``; the
        fan-out attaches the convergence profile and never re-derives status.
        """
        fanout_arms: list[FanoutArm] = []
        for worker, record in arms:
            profile = self._classifier.classify(record)
            fanout_arms.append(
                FanoutArm(
                    worker=worker,
                    run_id=record.run_id,
                    status=record.status,
                    profile=profile,
                )
            )
        return FanoutReport(
            repo=spec.repo,
            base_commit=spec.base_commit,
            arms=fanout_arms,
        )

    def run(
        self,
        spec: SweTaskSpec,
        workers: Iterable[str],
        dispatch: ArmDispatcher,
    ) -> FanoutReport:
        """Dispatch every worker arm against the same spec, then compare.

        ``dispatch(worker)`` must execute the governed pipeline for that arm
        and return its RunRecord. Arms run sequentially and independently: a
        worker is judged only on its own run's evidence.
        """
        worker_list = list(workers)
        if not worker_list:
            raise ValueError("Fan-out needs at least one worker arm.")
        arms = [(worker, dispatch(worker)) for worker in worker_list]
        return self.compare(spec, arms)


def render_fanout_markdown(report: FanoutReport) -> str:
    lines = [
        f"## Benchmark fan-out · {report.repo} @ {report.base_commit[:12]}",
        "",
        f"**Arms:** {report.total} · "
        f"**Correctness convergence:** {report.correctness_count}/{report.total} · "
        f"**Implicit (the gap):** {report.implicit_count}/{report.total}",
        "",
    ]
    if report.total:
        verdict = (
            "All arms agree on correctness."
            if report.correctness_count == report.total
            else (
                "No arm reached correctness."
                if report.correctness_count == 0
                else "MIXED outcome — some workers verified, some did not."
            )
        )
        lines.append(f"**Agreement:** {verdict}")
        lines.append("")
    lines.append("| Worker | Run | Status | Convergence | Implicit |")
    lines.append("|---|---|---|---|---|")
    for arm in report.arms:
        achieved = ", ".join(arm.profile.achieved) or "—"
        lines.append(
            f"| {arm.worker} | {arm.run_id[:12]} | {arm.status} | {achieved} | "
            f"{'yes' if arm.profile.is_implicit else 'no'} |"
        )
    if report.implicit_workers:
        lines.append("")
        lines.append(
            f"Implicit arms (stopped without a verification signal): "
            f"{', '.join(report.implicit_workers)}"
        )
    lines.append("")
    return "\n".join(lines)
