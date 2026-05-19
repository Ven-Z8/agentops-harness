from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.workload import evaluate_workload_gates
from app.schemas.run import RunRecord
from app.schemas.workload import WorkloadGateResult, WorkloadManifest


@dataclass(frozen=True)
class PortfolioEpisode:
    """Viewer-facing package that turns a harness run into portfolio evidence."""

    record: RunRecord
    workload: WorkloadManifest | None = None
    gate_result: WorkloadGateResult | None = None


def build_portfolio_episode(
    record: RunRecord,
    workload: WorkloadManifest | None = None,
) -> PortfolioEpisode:
    gate_result = evaluate_workload_gates(record, workload) if workload else None
    return PortfolioEpisode(record=record, workload=workload, gate_result=gate_result)


def render_portfolio_episode_markdown(episode: PortfolioEpisode) -> str:
    record = episode.record
    workload = episode.workload
    gate_result = episode.gate_result
    commands = record.test_results.commands
    successful_commands = [command for command in commands if command.exit_code == 0]
    failed_commands = [command for command in commands if command.exit_code != 0]
    edit_status = record.edit_result.status if record.edit_result else "observe_only"
    worker_command = record.edit_result.command if record.edit_result else "none"
    provider_events = [log for log in record.execution_logs if "provider" in log.lower()]
    guard_sections = []
    if record.evidence_report.unsupported_claim_count:
        guard_sections.append(
            "Evidence Guard flagged "
            f"{record.evidence_report.unsupported_claim_count} unsupported claim(s)."
        )
    if record.report_quality.findings:
        guard_sections.append(
            f"Report Quality Guard flagged {len(record.report_quality.findings)} issue(s)."
        )
    if not guard_sections:
        guard_sections.append("Evidence and report quality guards did not add blocking findings.")

    workload_name = workload.name if workload else "ad hoc harness run"
    gate_line = "not evaluated"
    if gate_result:
        gate_line = "passed" if gate_result.passed else "failed"

    lines = [
        f"# Portfolio Episode: {workload_name}",
        "",
        "## Why This Matters",
        (
            "This episode packages a real AgentOps Harness run as portfolio evidence: "
            "repo context, task intent, worker mode, validation commands, risk, guards, "
            "and final report are tied to one persisted run."
        ),
        "",
        "## Run",
        f"- Run ID: `{record.run_id}`",
        f"- Repository: `{record.repo_path}`",
        f"- Task: {record.task}",
        f"- Status: `{record.status}`",
        f"- Worker mode: `{edit_status}`",
        f"- Worker command: `{worker_command}`",
        f"- Started: `{record.started_at.isoformat()}`",
        f"- Completed: `{record.completed_at.isoformat()}`",
        "",
        "## Harness Signals",
        f"- Changed files: {len(record.changed_files)}",
        f"- Deleted files: {len(record.deleted_files)}",
        "- Test commands: "
        f"{len(commands)} total, {len(successful_commands)} passed, "
        f"{len(failed_commands)} failed",
        f"- Risk score: {record.risk_report.risk_score} ({record.risk_report.risk_level})",
        f"- Workload gates: {gate_line}",
        f"- Provider/tool events: {len(provider_events)}",
        "",
        "## Validation Commands",
    ]

    if commands:
        for command in commands:
            result = "passed" if command.exit_code == 0 else f"failed ({command.exit_code})"
            lines.append(f"- `{command.command}` -> {result}")
    else:
        lines.append("- No validation commands were recorded.")

    lines.extend(["", "## Guardrail Verdict"])
    for section in guard_sections:
        lines.append(f"- {section}")

    if gate_result and gate_result.reasons:
        lines.extend(["", "## Gate Failures"])
        for reason in gate_result.reasons:
            lines.append(f"- {reason}")

    if record.changed_files:
        lines.extend(["", "## Changed Files"])
        for path in record.changed_files:
            lines.append(f"- `{path}`")

    lines.extend(
        [
            "",
            "## Final Report",
            record.final_report.markdown.strip(),
            "",
        ]
    )
    return "\n".join(lines)


def write_portfolio_episode(episode: PortfolioEpisode, output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(render_portfolio_episode_markdown(episode), encoding="utf-8")
    return output_file
