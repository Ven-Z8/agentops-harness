"""Convergence-typed benchmark over harness runs (Code-as-Agent-Harness §4.3.2).

Maps the signals a harness run already produces onto the paper's six convergence
types, and flags the runs that *completed without verifying correctness* —
"implicit" convergence, which the paper calls the most significant gap.

Signal → convergence-type mapping (honest about what the harness does NOT do):
  correctness  — tests ran AND passed AND report claims are grounded
  security     — neither the risk guard nor the permission gate blocked the change
  score_based  — the report-quality critic accepted the report
  performance  — the harness measures no runtime metric → never reached
  consensus    — the harness runs no multi-agent vote → never reached
  implicit     — status == completed but correctness was NOT reached (the gap)
"""

from __future__ import annotations

from app.schemas.benchmark import (
    ALL_CONVERGENCE_TYPES,
    BenchmarkReport,
    ConvergenceProfile,
    ConvergenceType,
)
from app.schemas.run import RunRecord


class ConvergenceClassifier:
    def classify(self, record: RunRecord) -> ConvergenceProfile:
        achieved: list[ConvergenceType] = []
        notes: list[str] = []

        self._correctness(record, achieved, notes)
        self._security(record, achieved, notes)
        self._score_based(record, achieved)

        # performance and consensus are intentionally never reached: the harness
        # has no runtime metric and no multi-agent vote. Showing them at zero is
        # the point — the benchmark must reveal the gap, not paper over it.

        is_implicit = record.status == "completed" and "correctness" not in achieved
        if is_implicit:
            notes.append(
                "IMPLICIT convergence: the run completed without a correctness "
                "signal — it stopped without verifying it was done."
            )

        return ConvergenceProfile(
            run_id=record.run_id,
            task=record.task,
            achieved=achieved,
            is_implicit=is_implicit,
            notes=notes,
        )

    # -- per-type checks -----------------------------------------------------

    def _correctness(
        self,
        record: RunRecord,
        achieved: list[ConvergenceType],
        notes: list[str],
    ) -> None:
        if record.test_results.passed and record.evidence_report.grounded:
            achieved.append("correctness")
            return
        if not record.test_results.commands:
            notes.append("No validation commands ran; correctness was never gated.")
        elif not record.test_results.passed:
            notes.append("Validation commands failed; correctness not reached.")
        elif not record.evidence_report.grounded:
            notes.append("Report claims unsupported; correctness not grounded.")

    def _security(
        self,
        record: RunRecord,
        achieved: list[ConvergenceType],
        notes: list[str],
    ) -> None:
        if not record.risk_report.blocked and not record.permission_report.blocked:
            achieved.append("security")
        else:
            notes.append("A security gate blocked the change (risk or permission).")

    def _score_based(
        self,
        record: RunRecord,
        achieved: list[ConvergenceType],
    ) -> None:
        if record.report_quality.passed:
            achieved.append("score_based")

    # -- rendering -----------------------------------------------------------

    def render_markdown(self, report: BenchmarkReport) -> str:
        counts = report.type_counts
        lines = [
            "## Convergence-Typed Benchmark (paper §4.3.2)",
            "",
            f"**Runs:** {report.total} · "
            f"**Correctness convergence:** {report.correctness_rate:.0%} · "
            f"**Implicit convergence (the gap):** {report.implicit_rate:.0%}",
            "",
            "| Convergence type | Runs reached | Notes |",
            "|---|---:|---|",
        ]
        gap_notes = {
            "performance": "harness measures no runtime metric (gap)",
            "consensus": "harness runs no multi-agent vote (gap)",
            "implicit": "lower is better — stopped without verification",
        }
        for convergence_type in ALL_CONVERGENCE_TYPES:
            count = (
                report.implicit_count
                if convergence_type == "implicit"
                else counts[convergence_type]
            )
            note = gap_notes.get(convergence_type, "")
            lines.append(f"| {convergence_type} | {count} | {note} |")
        lines.append("")
        return "\n".join(lines)


def summarize_benchmark(profiles: list[ConvergenceProfile]) -> BenchmarkReport:
    return BenchmarkReport(profiles=profiles)
