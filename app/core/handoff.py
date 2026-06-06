from __future__ import annotations

from pathlib import Path

from app.agents.planner import Planner
from app.agents.repo_scanner import RepoScanner
from app.core.llm import LLMClient
from app.core.repo_graph import RepoGraphBuilder
from app.schemas.handoff import HandoffPlanStepBrief, WorkerHandoffPacket
from app.schemas.plan import ImplementationPlan
from app.schemas.run import RunRecord

WORKER_CONSTRAINTS = [
    "Do not rewrite unrelated files.",
    "Keep changes minimal and reversible; prefer small commits.",
    "Do not force-push, hard-reset, or delete git history.",
    "Run the verification commands exactly as listed before declaring done.",
    "If blocked, summarize blockers instead of speculative large refactors.",
]


def _verification_from_run(record: RunRecord) -> list[str]:
    return [cmd.command for cmd in record.test_results.commands]


def _verification_from_plan(plan: ImplementationPlan) -> list[str]:
    if plan.tests_to_run:
        return list(plan.tests_to_run)
    return ["python -m pytest -q"]


def _steps_brief(plan: ImplementationPlan) -> list[HandoffPlanStepBrief]:
    return [
        HandoffPlanStepBrief(
            id=step.id,
            title=step.title,
            description=step.description,
            files_to_inspect=list(step.files_to_inspect),
            files_to_edit=list(step.files_to_edit),
        )
        for step in plan.steps
    ]


def worker_handoff_from_run(record: RunRecord) -> WorkerHandoffPacket:
    verification = _verification_from_run(record) or _verification_from_plan(record.plan)
    edit_status: str | None = None
    if record.edit_result is not None:
        edit_status = record.edit_result.status

    return WorkerHandoffPacket(
        phase="completed_run",
        run_id=record.run_id,
        repo_path=record.repo_path,
        task=record.task,
        plan_summary=record.plan.summary,
        acceptance_criteria=list(record.plan.acceptance_criteria),
        plan_steps=_steps_brief(record.plan),
        tests_to_run=list(record.plan.tests_to_run),
        plan_risk_notes=list(record.plan.risk_notes),
        verification_commands=verification,
        harness_status=record.status,
        changed_files=list(record.changed_files),
        deleted_files=list(record.deleted_files),
        risk_score=record.risk_report.risk_score,
        risk_level=record.risk_report.risk_level,
        risk_blocked=record.risk_report.blocked,
        edit_result_status=edit_status,
    )


def draft_worker_handoff(
    repo_path: Path,
    task: str,
    *,
    llm_client: LLMClient | None = None,
) -> WorkerHandoffPacket:
    profile = RepoScanner().scan(repo_path)
    repo_graph = RepoGraphBuilder().build(repo_path)
    plan = Planner(llm_client=llm_client).create_plan(task, profile, repo_graph=repo_graph)
    verification = _verification_from_plan(plan)
    return WorkerHandoffPacket(
        phase="draft_pre_worker",
        run_id=None,
        repo_path=str(repo_path.resolve()),
        task=task,
        plan_summary=plan.summary,
        acceptance_criteria=list(plan.acceptance_criteria),
        plan_steps=_steps_brief(plan),
        tests_to_run=list(plan.tests_to_run),
        plan_risk_notes=list(plan.risk_notes),
        verification_commands=verification,
        harness_status="pending_verification",
        changed_files=[],
        deleted_files=[],
        risk_score=None,
        risk_level=None,
        risk_blocked=None,
        edit_result_status=None,
    )


def render_handoff_markdown(packet: WorkerHandoffPacket) -> str:
    banner = "# Worker handoff packet\n\n"
    if packet.phase == "draft_pre_worker":
        banner += (
            "> **Draft (pre-worker):** Observe-only harness slice. Run `agentops run` "
            "or `agentops edit` afterward to persist a full validated run.\n\n"
        )
    else:
        banner += (
            "> **Completed run snapshot:** Harness already executed through review "
            "and risk gates.\n\n"
        )

    lines: list[str] = [
        banner.rstrip(),
        "",
        "## Metadata",
        "",
        f"- Phase: `{packet.phase}`",
        f"- Repo: `{packet.repo_path}`",
    ]
    if packet.run_id:
        lines.append(f"- Run ID: `{packet.run_id}`")
    lines.extend(
        [
            f"- Harness status: `{packet.harness_status}`",
            "",
            "## Original task",
            "",
            packet.task.strip(),
            "",
            "## Plan summary",
            "",
            packet.plan_summary.strip(),
            "",
            "## Acceptance criteria",
            "",
            _bullet_list(packet.acceptance_criteria) or "- *(none listed)*",
            "",
            "## Suggested execution steps",
            "",
            _format_plan_steps(packet.plan_steps),
            "",
            "## Tests the harness associates with this task",
            "",
            _bullet_list(packet.tests_to_run) or "- *(none listed)*",
            "",
            "## Verification commands (exact)",
            "",
            _code_block_commands(packet.verification_commands),
            "",
            "## Plan risk notes",
            "",
            _bullet_list(packet.plan_risk_notes) or "- *(none listed)*",
            "",
            "## Worker constraints",
            "",
            _bullet_list(WORKER_CONSTRAINTS),
            "",
            "## Harness outcome (filled after a full run)",
            "",
            _run_outcome_table(packet),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _bullet_list(items: list[str]) -> str:
    if not items:
        return ""
    return "\n".join(f"- {line}" for line in items)


def _code_block_commands(commands: list[str]) -> str:
    if not commands:
        return "```bash\n(no commands captured — default: python -m pytest -q)\n```"
    inner = "\n".join(commands)
    return f"```bash\n{inner}\n```"


def _format_plan_steps(steps: list[HandoffPlanStepBrief]) -> str:
    if not steps:
        return "- *(no structured steps)*"
    blocks = []
    for step in steps:
        inspect = ", ".join(step.files_to_inspect) or "—"
        edit = ", ".join(step.files_to_edit) or "—"
        blocks.append(
            f"{step.id}. **{step.title}**\n   - {step.description}\n"
            f"   - Inspect: `{inspect}`\n   - Edit: `{edit}`"
        )
    return "\n\n".join(blocks)


def _run_outcome_table(packet: WorkerHandoffPacket) -> str:
    if packet.phase != "completed_run":
        return (
            "| Field | Value |\n|---|---|\n"
            "| changed_files | *(run harness to populate)* |\n"
            "| risk | *(pending)* |\n"
        )

    cf = ", ".join(packet.changed_files) or "—"
    df = ", ".join(packet.deleted_files) or "—"
    risk = packet.risk_level or "—"
    rs = packet.risk_score if packet.risk_score is not None else "—"
    blocked = packet.risk_blocked if packet.risk_blocked is not None else "—"
    edit_row = ""
    if packet.edit_result_status is not None:
        edit_row = f"| external worker | `{packet.edit_result_status}` |\n"
    return (
        "| Field | Value |\n|---|---|\n"
        f"| changed_files | `{cf}` |\n"
        f"| deleted_files | `{df}` |\n"
        f"| risk_level | `{risk}` |\n"
        f"| risk_score | `{rs}` |\n"
        f"| risk_blocked | `{blocked}` |\n"
        f"{edit_row}"
    )


def handoff_document_json(packet: WorkerHandoffPacket) -> dict:
    payload = packet.model_dump(mode="json")
    payload["constraints"] = WORKER_CONSTRAINTS
    payload["markdown"] = render_handoff_markdown(packet)
    return payload
