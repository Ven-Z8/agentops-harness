"""Evolution Agent — harness self-improvement (Code-as-Agent-Harness §3.5).

Reads the harness's own run history and proposes improvements to the *harness*,
not to any single task. It looks for recurring patterns the operator should act
on structurally:

  * missing validation across many runs  -> enforce validation commands
  * repeated failing tests               -> investigate flaky/failing suite
  * clustered security blocks            -> codify a policy for the hot area

Every proposal cites the run IDs that justify it, so the suggestion is inspectable
and falsifiable rather than a vibe.
"""

from __future__ import annotations

from app.schemas.evolution import EvolutionReport, Proposal
from app.schemas.run import RunRecord

# A pattern must recur at least this many times before it earns a proposal — one
# run is an anecdote, not a trend.
_MIN_OCCURRENCES = 2
# ...and account for at least this share of history before it is "dominant".
_DOMINANCE_FRACTION = 0.3


class EvolutionAgent:
    def analyze(self, records: list[RunRecord]) -> EvolutionReport:
        total = len(records)
        if total == 0:
            return EvolutionReport(runs_analyzed=0, proposals=[])

        proposals: list[Proposal] = []
        self._missing_validation(records, total, proposals)
        self._recurring_failures(records, proposals)
        self._clustered_blocks(records, proposals)

        return EvolutionReport(runs_analyzed=total, proposals=proposals)

    # -- pattern detectors ---------------------------------------------------

    def _missing_validation(
        self, records: list[RunRecord], total: int, proposals: list[Proposal]
    ) -> None:
        offenders = [
            r.run_id
            for r in records
            if r.status == "completed" and not r.test_results.commands
        ]
        count = len(offenders)
        if count >= _MIN_OCCURRENCES and count / total >= _DOMINANCE_FRACTION:
            proposals.append(
                Proposal(
                    code="enforce_validation_commands",
                    title="Enforce validation commands before completion",
                    rationale=(
                        f"{count} of {total} runs completed without running any "
                        "validation command (implicit convergence — the paper's most "
                        "significant gap). Make at least one test command mandatory, "
                        "or mark such runs as unverified rather than completed."
                    ),
                    priority="high",
                    evidence_run_ids=offenders,
                )
            )

    def _recurring_failures(
        self, records: list[RunRecord], proposals: list[Proposal]
    ) -> None:
        offenders = [
            r.run_id
            for r in records
            if r.test_results.commands and not r.test_results.passed
        ]
        if len(offenders) >= _MIN_OCCURRENCES:
            proposals.append(
                Proposal(
                    code="investigate_recurring_test_failures",
                    title="Investigate recurring test failures",
                    rationale=(
                        f"{len(offenders)} runs executed validation but the suite "
                        "failed. Triage whether the suite is flaky or the worker keeps "
                        "shipping incomplete changes before claiming completion."
                    ),
                    priority="medium",
                    evidence_run_ids=offenders,
                )
            )

    def _clustered_blocks(
        self, records: list[RunRecord], proposals: list[Proposal]
    ) -> None:
        offenders = [
            r.run_id
            for r in records
            if r.status == "blocked" or r.risk_report.blocked
        ]
        if len(offenders) >= _MIN_OCCURRENCES:
            proposals.append(
                Proposal(
                    code="codify_recurring_security_blocks",
                    title="Codify a policy for recurring security blocks",
                    rationale=(
                        f"{len(offenders)} runs were blocked by a security gate. "
                        "Recurring blocks in the same area suggest the policy should be "
                        "codified (explicit allow/deny rules or a pre-approval path) "
                        "rather than re-litigated each run."
                    ),
                    priority="medium",
                    evidence_run_ids=offenders,
                )
            )

    # -- rendering -----------------------------------------------------------

    def render_markdown(self, report: EvolutionReport) -> str:
        lines = [
            "## Evolution Agent Proposals (paper §3.5)",
            "",
            f"**Runs analyzed:** {report.runs_analyzed} · "
            f"**Proposals:** {len(report.proposals)}",
            "",
        ]
        if not report.has_proposals:
            lines.append("No structural improvements warranted — history looks healthy.")
            return "\n".join(lines)
        for proposal in report.proposals:
            lines.append(f"### [{proposal.priority}] {proposal.title} (`{proposal.code}`)")
            lines.append("")
            lines.append(proposal.rationale)
            lines.append("")
            lines.append(f"_Evidence runs: {', '.join(proposal.evidence_run_ids)}_")
            lines.append("")
        return "\n".join(lines)
