from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.evidence_guard import EvidenceGuard
from app.agents.permission_gate import PermissionGate
from app.agents.planner import Planner
from app.agents.pr_writer import PRWriter
from app.agents.repo_scanner import RepoScanner
from app.agents.report_quality_guard import ReportQualityGuard
from app.agents.reviewer import Reviewer
from app.agents.risk_guard import RiskGuard
from app.agents.verification_stack import VerificationStack
from app.core.conflict import ConflictAuditor
from app.core.edit_runner import ExternalWorkerRunner
from app.core.git_utils import collect_changed_files, collect_deleted_files, collect_diff_summary
from app.core.llm import LLMClient
from app.core.memory import ExperienceMemory
from app.core.repo_graph import RepoGraphBuilder
from app.core.state import AgentOpsGraphState
from app.core.storage import RunStorage
from app.core.test_runner import TestRunner
from app.core.workers.claude_worker import ClaudeCodeWorker
from app.core.workers.codex_worker import CodexWorker
from app.core.workers.opencode_worker import OpenCodeWorker
from app.schemas.memory import MemoryReport
from app.schemas.run import RunRecord


def append_logs(state: AgentOpsGraphState, *entries: str) -> list[str]:
    return [*state.get("execution_logs", []), *entries]


def scan_repo_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    profile = RepoScanner().scan(state["repo_path"])
    repo_graph = RepoGraphBuilder().build(state["repo_path"])
    return {
        "repo_profile": profile,
        "repo_graph": repo_graph,
        "execution_logs": append_logs(
            state,
            "scan_repo:start",
            "repo_graph:complete",
            "scan_repo:complete",
        ),
    }


def recall_experience_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    """Recall lessons from similar past runs before planning (§3.2.3)."""
    try:
        history = RunStorage(state["storage_path"]).list(limit=200)
    except Exception:
        history = []
    memory_report = ExperienceMemory().retrieve(state["task"], history, k=3)
    log = (
        "recall_experience:hit"
        if memory_report.has_recall
        else "recall_experience:miss"
    )
    return {
        "memory_report": memory_report,
        "execution_logs": append_logs(state, "recall_experience:start", log),
    }


def create_plan_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    logs = append_logs(state, "create_plan:start")
    memory_report = state.get("memory_report") or MemoryReport()
    lessons = memory_report.lessons
    try:
        plan = Planner(llm_client=state.get("llm_client")).create_plan(
            state["task"],
            state["repo_profile"],
            memory_lessons=lessons,
        )
    except Exception:
        plan = Planner().create_plan(
            state["task"], state["repo_profile"], memory_lessons=lessons
        )
        logs.append("provider_fallback:create_plan")
    logs.append("create_plan:complete")
    return {
        "plan": plan,
        "execution_logs": logs,
    }


def run_external_worker_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    worker_type = state.get("worker_type")
    worker_command = state.get("worker_command")
    timeout = state.get("worker_timeout_seconds") or 300
    allow_dirty = state.get("allow_dirty") or False

    if worker_type == "claude":
        edit_result = ClaudeCodeWorker().run(
            repo_path=state["repo_path"],
            task=state["task"],
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_type == "codex":
        edit_result = CodexWorker().run(
            repo_path=state["repo_path"],
            task=state["task"],
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_type == "opencode":
        edit_result = OpenCodeWorker().run(
            repo_path=state["repo_path"],
            task=state["task"],
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_command:
        edit_result = ExternalWorkerRunner().run(
            repo_path=state["repo_path"],
            task=state["task"],
            command_template=worker_command,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    else:
        return {"edit_result": None}

    return {
        "edit_result": edit_result,
        "execution_logs": append_logs(
            state,
            "run_external_worker:start",
            "run_external_worker:complete",
        ),
    }


def collect_diff_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    repo_path = state["repo_path"]
    return {
        "changed_files": collect_changed_files(repo_path),
        "deleted_files": collect_deleted_files(repo_path),
        "diff_summary": collect_diff_summary(repo_path),
        "execution_logs": append_logs(state, "collect_diff:start", "collect_diff:complete"),
    }


def run_tests_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    test_results = TestRunner().run(
        state["repo_path"],
        commands=state.get("test_commands"),
    )
    return {
        "test_results": test_results,
        "execution_logs": append_logs(state, "run_tests:start", "run_tests:complete"),
    }


def review_diff_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    logs = append_logs(state, "review_diff:start")
    try:
        review_report = Reviewer(llm_client=state.get("llm_client")).review(
            state["changed_files"],
            state["test_results"],
        )
    except Exception:
        review_report = Reviewer().review(state["changed_files"], state["test_results"])
        logs.append("provider_fallback:review_diff")
    logs.append("review_diff:complete")
    return {
        "review_report": review_report,
        "execution_logs": logs,
    }


def assess_risk_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    risk_report = RiskGuard().assess(
        state["changed_files"],
        state["deleted_files"],
        state["test_results"],
    )
    return {
        "risk_report": risk_report,
        "execution_logs": append_logs(state, "assess_risk:start", "assess_risk:complete"),
    }


def classify_permissions_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    permission_report = PermissionGate().classify(
        changed_files=state["changed_files"],
        deleted_files=state["deleted_files"],
        commands=state.get("test_commands") or [],
    )
    return {
        "permission_report": permission_report,
        "execution_logs": append_logs(
            state,
            "classify_permissions:start",
            "classify_permissions:complete",
        ),
    }


def write_report_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    logs = append_logs(state, "write_report:start")
    try:
        final_report = PRWriter(llm_client=state.get("llm_client")).write(
            task=state["task"],
            plan=state["plan"],
            changed_files=state["changed_files"],
            test_results=state["test_results"],
            review_report=state["review_report"],
            risk_report=state["risk_report"],
            edit_result=state.get("edit_result"),
        )
    except Exception:
        final_report = PRWriter().write(
            task=state["task"],
            plan=state["plan"],
            changed_files=state["changed_files"],
            test_results=state["test_results"],
            review_report=state["review_report"],
            risk_report=state["risk_report"],
            edit_result=state.get("edit_result"),
        )
        logs.append("provider_fallback:write_report")
    logs.append("write_report:complete")
    return {
        "final_report": final_report,
        "execution_logs": logs,
    }


def check_report_quality_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    quality_guard = ReportQualityGuard()
    quality_report = quality_guard.check(state["final_report"])
    final_report = state["final_report"]

    if not quality_report.passed:
        final_report = PRWriter().write(
            task=state["task"],
            plan=state["plan"],
            changed_files=state["changed_files"],
            test_results=state["test_results"],
            review_report=state["review_report"],
            risk_report=state["risk_report"],
            edit_result=state.get("edit_result"),
        )
        quality_report = quality_guard.mark_fallback(quality_report)

    final_report = quality_guard.append_to_report(final_report, quality_report)
    return {
        "report_quality": quality_report,
        "final_report": final_report,
        "execution_logs": append_logs(
            state,
            "check_report_quality:start",
            "check_report_quality:complete",
        ),
    }


def check_evidence_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    evidence_guard = EvidenceGuard()
    evidence_report = evidence_guard.check(
        final_report=state["final_report"],
        changed_files=state["changed_files"],
        test_results=state["test_results"],
    )
    final_report = evidence_guard.append_to_report(state["final_report"], evidence_report)
    return {
        "evidence_report": evidence_report,
        "final_report": final_report,
        "execution_logs": append_logs(
            state,
            "check_evidence:start",
            "check_evidence:complete",
        ),
    }


def assemble_verification_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    verification_stack = VerificationStack()
    bundle = verification_stack.assemble(
        changed_files=state["changed_files"],
        test_results=state["test_results"],
        review_report=state["review_report"],
        risk_report=state["risk_report"],
        evidence_report=state["evidence_report"],
    )
    final_report = verification_stack.append_to_report(state["final_report"], bundle)
    return {
        "verification_bundle": bundle,
        "final_report": final_report,
        "execution_logs": append_logs(
            state,
            "assemble_verification:start",
            "assemble_verification:complete",
        ),
    }


def audit_conflicts_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    auditor = ConflictAuditor()
    conflict_report = auditor.audit(
        final_report=state["final_report"],
        test_results=state["test_results"],
        evidence_report=state["evidence_report"],
        risk_report=state["risk_report"],
        permission_report=state["permission_report"],
        plan=state["plan"],
    )
    final_report = auditor.append_to_report(state["final_report"], conflict_report)
    return {
        "conflict_report": conflict_report,
        "final_report": final_report,
        "execution_logs": append_logs(
            state,
            "audit_conflicts:start",
            "audit_conflicts:complete",
        ),
    }


def build_workflow_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentOpsGraphState)
    graph.add_node("scan_repo", scan_repo_node)
    graph.add_node("recall_experience", recall_experience_node)
    graph.add_node("create_plan", create_plan_node)
    graph.add_node("run_external_worker", run_external_worker_node)
    graph.add_node("collect_diff", collect_diff_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("review_diff", review_diff_node)
    graph.add_node("assess_risk", assess_risk_node)
    graph.add_node("classify_permissions", classify_permissions_node)
    graph.add_node("write_report", write_report_node)
    graph.add_node("check_report_quality", check_report_quality_node)
    graph.add_node("check_evidence", check_evidence_node)
    graph.add_node("assemble_verification", assemble_verification_node)
    graph.add_node("audit_conflicts", audit_conflicts_node)

    graph.add_edge(START, "scan_repo")
    graph.add_edge("scan_repo", "recall_experience")
    graph.add_edge("recall_experience", "create_plan")
    graph.add_edge("create_plan", "run_external_worker")
    graph.add_edge("run_external_worker", "collect_diff")
    graph.add_edge("collect_diff", "run_tests")
    graph.add_edge("run_tests", "review_diff")
    graph.add_edge("review_diff", "assess_risk")
    graph.add_edge("assess_risk", "classify_permissions")
    graph.add_edge("classify_permissions", "write_report")
    graph.add_edge("write_report", "check_report_quality")
    graph.add_edge("check_report_quality", "check_evidence")
    graph.add_edge("check_evidence", "assemble_verification")
    graph.add_edge("assemble_verification", "audit_conflicts")
    graph.add_edge("audit_conflicts", END)
    return graph.compile()


def run_harness(
    repo_path: Path,
    task: str,
    storage_path: Path,
    test_commands: list[str] | None = None,
    llm_client: LLMClient | None = None,
    worker_command: str | None = None,
    worker_type: str | None = None,
    worker_timeout_seconds: int = 300,
    allow_dirty: bool = False,
) -> RunRecord:
    started_at = datetime.now(UTC)
    run_id = uuid4().hex
    graph_state = build_workflow_graph().invoke(
        {
            "run_id": run_id,
            "task": task,
            "repo_path": repo_path,
            "storage_path": storage_path,
            "test_commands": test_commands,
            "llm_client": llm_client,
            "worker_command": worker_command,
            "worker_type": worker_type,
            "worker_timeout_seconds": worker_timeout_seconds,
            "allow_dirty": allow_dirty,
            "execution_logs": [],
        },
        config={"configurable": {"thread_id": run_id}},
    )

    risk_report = graph_state["risk_report"]
    permission_report = graph_state["permission_report"]
    edit_result = graph_state.get("edit_result")
    status = "blocked" if (risk_report.blocked or permission_report.blocked) else "completed"
    if status == "completed" and edit_result is not None and edit_result.status != "completed":
        status = "failed"
    record = RunRecord(
        run_id=run_id,
        task=task,
        repo_path=str(repo_path.resolve()),
        repo_profile=graph_state["repo_profile"],
        repo_graph=graph_state["repo_graph"],
        memory_report=graph_state.get("memory_report") or MemoryReport(),
        plan=graph_state["plan"],
        changed_files=graph_state["changed_files"],
        deleted_files=graph_state["deleted_files"],
        diff_summary=graph_state["diff_summary"],
        test_results=graph_state["test_results"],
        review_report=graph_state["review_report"],
        risk_report=risk_report,
        permission_report=permission_report,
        final_report=graph_state["final_report"],
        report_quality=graph_state["report_quality"],
        evidence_report=graph_state["evidence_report"],
        verification_bundle=graph_state["verification_bundle"],
        conflict_report=graph_state["conflict_report"],
        edit_result=edit_result,
        execution_logs=graph_state["execution_logs"],
        token_usage={"tokens_in": 0, "tokens_out": 0},
        status=status,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    RunStorage(storage_path).save(record)
    return record
