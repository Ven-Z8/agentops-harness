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
from app.agents.product_reviewer import ProductReviewer
from app.agents.repo_scanner import RepoScanner
from app.agents.report_quality_guard import ReportQualityGuard
from app.agents.reviewer import Reviewer
from app.agents.risk_guard import RiskGuard
from app.agents.verification_stack import VerificationStack
from app.core.conflict import ConflictAuditor
from app.core.edit_runner import ExternalWorkerRunner
from app.core.git_utils import (
    collect_changed_files,
    collect_deleted_files,
    collect_diff_body,
    collect_diff_summary,
    run_git,
)
from app.core.goal_model import GoalModelError, load_goal_model
from app.core.llm import LLMClient
from app.core.memory import ExperienceMemory
from app.core.repo_graph import RepoGraphBuilder
from app.core.repo_graph.impact import ChangedSubgraphBuilder, render_changed_subgraph_markdown
from app.core.run_artifacts import RunArtifactWriter, append_artifact_links, artifact_dir_for_run
from app.core.state import AgentOpsGraphState
from app.core.storage import RunStorage
from app.core.test_runner import TestRunner
from app.core.workers.claude_worker import ClaudeCodeWorker
from app.core.workers.codex_worker import CodexWorker
from app.core.workers.opencode_worker import OpenCodeWorker
from app.core.workers.openhands_worker import OpenHandsWorker
from app.core.workspace.base import Workspace
from app.core.workspace.docker import DockerWorkspace
from app.core.workspace.local import LocalWorkspace
from app.schemas.edit import ExternalEditResult
from app.schemas.governance import PreDispatchDecision
from app.schemas.memory import MemoryReport
from app.schemas.run import RunRecord
from app.schemas.test import TestRunSummary
from app.schemas.workspace import PrepareResult


def append_logs(state: AgentOpsGraphState, *entries: str) -> list[str]:
    return [*state.get("execution_logs", []), *entries]


def make_workspace(state: AgentOpsGraphState) -> Workspace:
    """Return the Workspace implementation for this run.

    ``--workspace docker`` runs validation in an isolated container; the default
    LocalWorkspace preserves today's host behaviour exactly.  When
    ``isolation="full"`` the DockerWorkspace is configured for full-isolation mode
    (no bind-mount; worker runs inside; extract_permitted controls what lands on host).
    """
    if state.get("workspace_kind") == "docker":
        isolation = state.get("isolation") or "validation"
        return DockerWorkspace(state["repo_path"], isolation=isolation)
    return LocalWorkspace(state["repo_path"])


def prepare_workspace_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    logs = append_logs(state, "prepare_workspace:start")
    ws = make_workspace(state)
    result = ws.prepare()
    if not result.ok:
        logs.append("workspace_blocked")
    logs.append("prepare_workspace:complete")
    return {
        "workspace": ws,
        "workspace_report": result,
        "execution_logs": logs,
    }


def pre_dispatch_gate_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    import shlex

    from app.core.security import is_sensitive_path

    # Pre-dispatch enforcement only applies when a worker will actually run.
    # Observe mode (no worker) never blocks — there is nothing to dispatch.
    has_worker = bool(state.get("worker_command") or state.get("worker_type"))
    if not has_worker:
        return {
            "pre_dispatch": PreDispatchDecision(),
            "execution_logs": append_logs(state, "pre_dispatch:observe"),
        }

    # Block on the EXPLICIT worker command targeting a sensitive path — a precise signal.
    # The planner's files_to_edit is intentionally NOT used: it over-lists (whole test
    # trees, etc.), so it produces false blocks. For --worker-type workers (which decide
    # their own edits), post-edit revert-on-deny and the sandbox provide enforcement.
    command = state.get("worker_command") or ""
    try:
        command_tokens = set(shlex.split(command))
    except ValueError:
        command_tokens = set(command.split())
    denied = sorted({p for p in command_tokens if is_sensitive_path(p)})

    decision = PreDispatchDecision(
        blocked=bool(denied),
        denied_paths=denied,
        reason=f"Worker command targets sensitive paths: {denied}" if denied else "",
    )
    log = "pre_dispatch:blocked" if denied else "pre_dispatch:ok"
    return {"pre_dispatch": decision, "execution_logs": append_logs(state, log)}


def scan_repo_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    profile = RepoScanner().scan(state["repo_path"])
    repo_graph = RepoGraphBuilder().build(state["repo_path"])
    try:
        goal_model = load_goal_model(state["repo_path"])
        goal_log = "goal_model:loaded" if goal_model else "goal_model:absent"
    except GoalModelError:
        goal_model = None
        goal_log = "goal_model:invalid"
    return {
        "repo_profile": profile,
        "repo_graph": repo_graph,
        "goal_model": goal_model,
        "execution_logs": append_logs(
            state,
            "scan_repo:start",
            "repo_graph:complete",
            goal_log,
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
    repo_graph = state.get("repo_graph")
    try:
        plan = Planner(llm_client=state.get("llm_client")).create_plan(
            state["task"],
            state["repo_profile"],
            repo_graph=repo_graph,
            memory_lessons=lessons,
        )
    except Exception:
        plan = Planner().create_plan(
            state["task"],
            state["repo_profile"],
            repo_graph=repo_graph,
            memory_lessons=lessons,
        )
        logs.append("provider_fallback:create_plan")
    logs.append("create_plan:complete")
    return {
        "plan": plan,
        "execution_logs": logs,
    }


def run_external_worker_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    from app.core.security import is_sensitive_path

    # Increment attempt counter (starts at 0 in initial state, so first run → 1).
    attempts = state.get("attempts", 0) + 1

    # Sandbox (full isolation) runs the worker INSIDE the container, which only
    # supports an explicit --worker-command for now. The built-in worker types
    # (codex/claude/opencode/openhands) are not installed in the sandbox image yet,
    # so block the combination explicitly instead of silently running on the host
    # (which would not be sandboxed) or producing no edits. Checked first, so the
    # invalid combination is reported regardless of workspace preparation.
    if (
        (state.get("isolation") or "validation") == "full"
        and state.get("worker_type")
        and not state.get("worker_command")
    ):
        wt = state.get("worker_type")
        return {
            "attempts": attempts,
            "edit_result": ExternalEditResult(
                status="blocked",
                command=f"--worker-type {wt} --sandbox",
                stderr=(
                    "Sandbox mode (--sandbox) runs the worker inside the container and "
                    f"currently supports --worker-command only; the built-in '{wt}' worker "
                    "is not installed in the sandbox image yet. Use --worker-command for "
                    "sandboxed runs, or drop --sandbox to run the worker on the host with "
                    "isolated validation (--workspace docker)."
                ),
            ),
            "sandbox_blocked": [],
            "execution_logs": append_logs(state, "worker_blocked:sandbox_worker_type_unsupported"),
        }

    # Skip when workspace could not be prepared.
    if not state.get("workspace_report", PrepareResult()).ok:
        return {
            "attempts": attempts,
            "edit_result": None,
            "sandbox_blocked": [],
            "execution_logs": append_logs(state, "worker_skipped:workspace_not_ready"),
        }

    # Skip when pre-dispatch gate blocked the plan.
    if state.get("pre_dispatch", PreDispatchDecision()).blocked:
        return {
            "attempts": attempts,
            "edit_result": None,
            "sandbox_blocked": [],
            "execution_logs": append_logs(state, "worker_skipped:pre_dispatch_blocked"),
        }

    worker_type = state.get("worker_type")
    worker_command = state.get("worker_command")
    timeout = state.get("worker_timeout_seconds") or 300
    # On retries (attempts > 1), the repo will already have changes from the previous
    # attempt, so always allow dirty on subsequent attempts.
    allow_dirty = (state.get("allow_dirty") or False) or (attempts > 1)

    # If retry_feedback is set, append it to the task so the worker knows what failed.
    task = state["task"]
    retry_feedback = state.get("retry_feedback") or ""
    if retry_feedback:
        task = f"{task}\n\n[Retry feedback from previous attempt]:\n{retry_feedback}"

    # ------------------------------------------------------------------
    # Full-isolation sandbox path: run worker INSIDE the container, then
    # extract only permitted changes back to the host.
    # ------------------------------------------------------------------
    isolation = state.get("isolation") or "validation"
    workspace = state.get("workspace")
    if isolation == "full" and isinstance(workspace, DockerWorkspace) and worker_command:
        import shlex

        argv = shlex.split(worker_command)
        # Run the worker entirely inside the sandbox container (no host execution).
        cmd_result = workspace.run_worker(argv, timeout)
        edit_result = ExternalEditResult(
            status="completed" if cmd_result.exit_code == 0 else "failed",
            command=cmd_result.command,
            exit_code=cmd_result.exit_code,
            stdout=cmd_result.stdout,
            stderr=cmd_result.stderr,
            duration_seconds=cmd_result.duration_seconds,
        )

        extracted, blocked = workspace.extract_permitted(is_sensitive_path)
        logs = append_logs(
            state,
            "run_external_worker:start",
            f"sandbox:extracted {len(extracted)} blocked {len(blocked)}",
            "run_external_worker:complete",
        )
        return {
            "attempts": attempts,
            "edit_result": edit_result,
            "sandbox_blocked": blocked,
            "execution_logs": logs,
        }

    # ------------------------------------------------------------------
    # Standard (non-sandbox) paths: unchanged.
    # ------------------------------------------------------------------
    sandbox_blocked: list[str] = []

    if worker_type == "claude":
        edit_result = ClaudeCodeWorker().run(
            repo_path=state["repo_path"],
            task=task,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_type == "codex":
        edit_result = CodexWorker().run(
            repo_path=state["repo_path"],
            task=task,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_type == "opencode":
        edit_result = OpenCodeWorker().run(
            repo_path=state["repo_path"],
            task=task,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_type == "openhands":
        edit_result = OpenHandsWorker().run(
            repo_path=state["repo_path"],
            task=task,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    elif worker_command:
        edit_result = ExternalWorkerRunner().run(
            repo_path=state["repo_path"],
            task=task,
            command_template=worker_command,
            timeout_seconds=timeout,
            allow_dirty=allow_dirty,
        )
    else:
        return {"attempts": attempts, "edit_result": None, "sandbox_blocked": []}

    return {
        "attempts": attempts,
        "edit_result": edit_result,
        "sandbox_blocked": sandbox_blocked,
        "execution_logs": append_logs(
            state,
            "run_external_worker:start",
            "run_external_worker:complete",
        ),
    }


def collect_diff_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    # Task 3: route through the workspace abstraction when available so that
    # DockerWorkspace can exec git commands inside the container.  LocalWorkspace
    # delegates to the same git_utils helpers, so behavior is identical.
    # Deleted files are not part of the Workspace.read_changes() contract
    # (they need a separate git-status pass); continue to call git_utils directly
    # for that one field regardless of workspace kind.
    ws = state.get("workspace")
    repo_path = state["repo_path"]
    if ws is not None:
        changed_files, diff_summary, _diff_body = ws.read_changes()
    else:
        changed_files = collect_changed_files(repo_path)
        diff_summary = collect_diff_summary(repo_path)
    deleted_files = collect_deleted_files(repo_path)
    return {
        "changed_files": changed_files,
        "deleted_files": deleted_files,
        "diff_summary": diff_summary,
        "execution_logs": append_logs(state, "collect_diff:start", "collect_diff:complete"),
    }


def enforce_permissions_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    """Revert files the worker changed that violate path-based policy.

    Edit-mode only: when no worker ran (edit_result is None), this is a no-op.
    Reverted file names are stored in the state so classify_permissions can fold
    them into the single PermissionReport that reaches RunRecord.
    """
    from app.core.security import is_sensitive_path

    if state.get("edit_result") is None:
        return {
            "enforced_reverts": [],
            "execution_logs": append_logs(state, "enforce_permissions:skip"),
        }

    repo_path = state["repo_path"]
    reverted: list[str] = []

    for f in list(state.get("changed_files", [])):
        if not is_sensitive_path(f):
            continue
        file_path = repo_path / f
        # Check if the file is tracked in git (exists in HEAD).
        ls_result = run_git(repo_path, ["ls-files", "--error-unmatch", f])
        if ls_result.returncode == 0:
            # Tracked file — restore to HEAD state.
            run_git(repo_path, ["checkout", "--", f])
        else:
            # Untracked new file — delete it.
            if file_path.exists():
                file_path.unlink()
        reverted.append(f)

    # Re-read changes after reverts so downstream nodes see the cleaned state.
    ws = state.get("workspace")
    if ws is not None:
        changed_files, diff_summary, _diff_body = ws.read_changes()
    else:
        changed_files = collect_changed_files(repo_path)
        diff_summary = collect_diff_summary(repo_path)

    return {
        "changed_files": changed_files,
        "diff_summary": diff_summary,
        "enforced_reverts": reverted,
        "execution_logs": append_logs(
            state,
            "enforce_permissions:start",
            f"enforce_permissions:reverted={reverted}",
            "enforce_permissions:complete",
        ),
    }


def build_changed_subgraph_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    changed_subgraph = ChangedSubgraphBuilder().build(
        state["repo_graph"],
        changed_files=state["changed_files"],
        deleted_files=state["deleted_files"],
        fallback_validation=state["plan"].tests_to_run,
    )
    return {
        "changed_subgraph": changed_subgraph,
        "execution_logs": append_logs(
            state,
            "build_changed_subgraph:start",
            "build_changed_subgraph:complete",
        ),
    }


def run_tests_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    # Honor the plan-as-contract: explicit test_commands override, otherwise
    # run the validation the planner selected (e.g. `uv run pytest` for a uv
    # project) instead of falling back to the hardcoded default.
    commands = state.get("test_commands") or state["plan"].tests_to_run or None
    timeout = state.get("test_timeout_seconds") or 300
    workspace = state.get("workspace")
    if state.get("workspace_kind") == "docker" and workspace is not None:
        # Run validation inside the isolated container (reproducible deps).
        test_results = _run_tests_in_workspace(workspace, commands, timeout)
    else:
        # Local path: unchanged — TestRunner keeps its process-group/timeout semantics.
        runner_kwargs: dict = {"commands": commands}
        if state.get("test_timeout_seconds"):
            runner_kwargs["timeout_seconds"] = state["test_timeout_seconds"]
        test_results = TestRunner().run(state["repo_path"], **runner_kwargs)
    return {
        "test_results": test_results,
        "execution_logs": append_logs(state, "run_tests:start", "run_tests:complete"),
    }


def _run_tests_in_workspace(
    workspace: Workspace, commands: list[str] | None, timeout: int
) -> TestRunSummary:
    import shlex

    selected = commands or ["python -m pytest -q"]
    results = [workspace.run(shlex.split(command), timeout) for command in selected]
    return TestRunSummary(commands=results)


def check_convergence_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    """Decide whether the loop has converged or needs another attempt.

    Observe mode (edit_result is None) → always converged, loop exits immediately.
    Edit mode: converged when tests passed OR attempts reached max_attempts.
    retry_feedback is set to the truncated stderr of failed test commands so the
    worker can act on it on the next attempt.
    """
    edit_result = state.get("edit_result")
    # Observe mode: no worker ran — short-circuit, converged immediately.
    if edit_result is None:
        return {
            "converged": True,
            "retry_feedback": "",
            "execution_logs": append_logs(state, "check_convergence:skip"),
        }

    test_results = state.get("test_results")
    passed = test_results.passed if test_results is not None else True
    attempts = state.get("attempts", 1)
    max_attempts = state.get("max_attempts", 2)

    # converged = tests passed (regardless of attempt count).
    # The router uses _is_retriable_failure + attempts to decide retry vs proceed,
    # so env/infra failures (can't run, no tests, timeout) don't trigger pointless retries.
    converged = passed

    retry_feedback = ""
    if _is_retriable_failure(state) and attempts < max_attempts:
        # Collect truncated stderr from failed commands.
        failed_outputs: list[str] = []
        if test_results is not None:
            for cmd in test_results.commands:
                if cmd.exit_code != 0:
                    output = (cmd.stderr or cmd.stdout or "").strip()
                    failed_outputs.append(output[:500])
        retry_feedback = "\n---\n".join(failed_outputs) if failed_outputs else "Validation failed."

    return {
        "converged": converged,
        "retry_feedback": retry_feedback,
        "execution_logs": append_logs(
            state,
            "check_convergence:start",
            f"check_convergence:converged={converged}",
        ),
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
    # Fold in any files already reverted by enforce_permissions_node so the
    # single PermissionReport reaching RunRecord carries the full enforcement record.
    enforced_reverts = state.get("enforced_reverts") or []
    if enforced_reverts:
        permission_report = permission_report.model_copy(
            update={"enforced_reverts": list(enforced_reverts)}
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
    final_report.markdown = (
        final_report.markdown.rstrip()
        + render_changed_subgraph_markdown(state["changed_subgraph"])
    )
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
        risk_report=state["risk_report"],
        changed_subgraph=state["changed_subgraph"],
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


def build_product_review_node(state: AgentOpsGraphState) -> AgentOpsGraphState:
    logs = append_logs(state, "build_product_review:start")
    kwargs = dict(
        task=state["task"],
        plan=state["plan"],
        changed_files=state["changed_files"],
        diff_summary=state["diff_summary"],
        diff_body=collect_diff_body(state["repo_path"]),
        changed_subgraph=state.get("changed_subgraph"),
        test_results=state["test_results"],
        goal_model=state.get("goal_model"),
        target_goal_id=state.get("target_goal_id"),
    )
    reviewer = ProductReviewer(llm_client=state.get("llm_client"))
    try:
        review = reviewer.review(**kwargs)
    except Exception:
        review = ProductReviewer().review(**kwargs)
        logs.append("provider_fallback:build_product_review")
    final_report = reviewer.append_to_report(state["final_report"], review)
    logs.append("build_product_review:complete")
    return {
        "product_review": review,
        "final_report": final_report,
        "execution_logs": logs,
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


def _is_retriable_failure(state: AgentOpsGraphState) -> bool:
    """A failure is worth a worker retry only when tests genuinely RAN and FAILED.

    A test command exit code of 1 means tests executed and failed — the worker can
    fix that. Environment/infra failures are NOT the worker's fault and retrying is
    pointless: exit 2 (can't run / collection error), 5 (no tests collected),
    124 (timeout), 127 (command not found). Treat those as non-retriable.
    """
    test_results = state.get("test_results")
    if test_results is None or test_results.passed:
        return False
    return any(cmd.exit_code == 1 for cmd in test_results.commands)


def _route_convergence(state: AgentOpsGraphState) -> str:
    """Router for check_convergence conditional edge."""
    if state.get("edit_result") is None:
        return "proceed"
    attempts = state.get("attempts", 1)
    max_attempts = state.get("max_attempts", 2)
    if _is_retriable_failure(state) and attempts < max_attempts:
        return "retry"
    return "proceed"


def build_workflow_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentOpsGraphState)
    graph.add_node("scan_repo", scan_repo_node)
    graph.add_node("recall_experience", recall_experience_node)
    graph.add_node("create_plan", create_plan_node)
    graph.add_node("prepare_workspace", prepare_workspace_node)
    graph.add_node("pre_dispatch_gate", pre_dispatch_gate_node)
    graph.add_node("run_external_worker", run_external_worker_node)
    graph.add_node("collect_diff", collect_diff_node)
    graph.add_node("enforce_permissions", enforce_permissions_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("check_convergence", check_convergence_node)
    graph.add_node("build_changed_subgraph", build_changed_subgraph_node)
    graph.add_node("review_diff", review_diff_node)
    graph.add_node("assess_risk", assess_risk_node)
    graph.add_node("classify_permissions", classify_permissions_node)
    graph.add_node("write_report", write_report_node)
    graph.add_node("check_report_quality", check_report_quality_node)
    graph.add_node("check_evidence", check_evidence_node)
    graph.add_node("build_product_review", build_product_review_node)
    graph.add_node("assemble_verification", assemble_verification_node)
    graph.add_node("audit_conflicts", audit_conflicts_node)

    graph.add_edge(START, "scan_repo")
    graph.add_edge("scan_repo", "recall_experience")
    graph.add_edge("recall_experience", "create_plan")
    graph.add_edge("create_plan", "prepare_workspace")
    graph.add_edge("prepare_workspace", "pre_dispatch_gate")
    graph.add_edge("pre_dispatch_gate", "run_external_worker")
    # Loop body: worker → collect → enforce → tests → check_convergence
    graph.add_edge("run_external_worker", "collect_diff")
    graph.add_edge("collect_diff", "enforce_permissions")
    graph.add_edge("enforce_permissions", "run_tests")
    graph.add_edge("run_tests", "check_convergence")
    # Conditional: retry goes back to run_external_worker; proceed exits loop
    graph.add_conditional_edges(
        "check_convergence",
        _route_convergence,
        {"retry": "run_external_worker", "proceed": "build_changed_subgraph"},
    )
    # Post-loop: heavy analysis runs once after convergence
    graph.add_edge("build_changed_subgraph", "review_diff")
    graph.add_edge("review_diff", "assess_risk")
    graph.add_edge("assess_risk", "classify_permissions")
    graph.add_edge("classify_permissions", "write_report")
    graph.add_edge("write_report", "check_report_quality")
    graph.add_edge("check_report_quality", "check_evidence")
    graph.add_edge("check_evidence", "build_product_review")
    graph.add_edge("build_product_review", "assemble_verification")
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
    target_goal_id: str | None = None,
    test_timeout_seconds: int | None = None,
    workspace_kind: str = "local",
    isolation: str = "validation",
    max_attempts: int = 1,
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
            "test_timeout_seconds": test_timeout_seconds,
            "target_goal_id": target_goal_id,
            "workspace_kind": workspace_kind,
            "isolation": isolation,
            "execution_logs": [],
            # Retry loop seeds
            "attempts": 0,
            "max_attempts": max_attempts,
            "retry_feedback": "",
            "converged": True,
            "sandbox_blocked": [],
        },
        config={
            "configurable": {"thread_id": run_id},
            "recursion_limit": 50,
        },
    )

    # Tear down any isolated workspace (e.g. Docker container) so nothing leaks.
    workspace = graph_state.get("workspace")
    if workspace is not None:
        workspace.cleanup()

    risk_report = graph_state["risk_report"]
    permission_report = graph_state["permission_report"]
    pre_dispatch = graph_state.get("pre_dispatch") or PreDispatchDecision()
    edit_result = graph_state.get("edit_result")
    status: str
    if pre_dispatch.blocked or risk_report.blocked or permission_report.blocked:
        status = "blocked"
    else:
        status = "completed"
    if status == "completed" and edit_result is not None and edit_result.status != "completed":
        status = "failed"
    # A worker was requested but never ran (e.g. workspace not ready) — don't report a
    # bare "completed" with no edits; surface that the worker was blocked.
    if (
        status == "completed"
        and edit_result is None
        and (worker_type or worker_command)
        and not graph_state["workspace_report"].ok
    ):
        status = "blocked"
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
        changed_subgraph=graph_state["changed_subgraph"],
        test_results=graph_state["test_results"],
        review_report=graph_state["review_report"],
        risk_report=risk_report,
        permission_report=permission_report,
        final_report=graph_state["final_report"],
        report_quality=graph_state["report_quality"],
        evidence_report=graph_state["evidence_report"],
        verification_bundle=graph_state["verification_bundle"],
        conflict_report=graph_state["conflict_report"],
        workspace_report=graph_state.get("workspace_report") or PrepareResult(),
        pre_dispatch=pre_dispatch,
        product_review=graph_state["product_review"],
        edit_result=edit_result,
        execution_logs=graph_state["execution_logs"],
        token_usage={"tokens_in": 0, "tokens_out": 0},
        status=status,
        attempts=graph_state.get("attempts", 1),
        converged=graph_state.get("converged", True),
        sandbox_blocked=graph_state.get("sandbox_blocked") or [],
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    artifact_dir = artifact_dir_for_run(storage_path, run_id)
    record = append_artifact_links(record, artifact_dir)
    RunStorage(storage_path).save(record)
    RunArtifactWriter().write(record, storage_path)
    return record
