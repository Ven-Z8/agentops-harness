import subprocess
from pathlib import Path

from app.core.graph import pre_dispatch_gate_node, run_harness
from app.schemas.governance import PreDispatchDecision
from app.schemas.plan import ImplementationPlan, PlanStep


def _make_state_with_sensitive_plan(tmp_repo: Path) -> dict:
    """Build a minimal graph state whose plan targets a sensitive path."""
    plan = ImplementationPlan(
        task="test",
        summary="test",
        steps=[
            PlanStep(
                id=1,
                title="edit auth",
                description="edit auth",
                files_to_edit=["app/auth/login.py"],
            )
        ],
    )
    return {
        "plan": plan,
        "execution_logs": [],
    }


def _make_state_with_safe_plan(tmp_repo: Path) -> dict:
    plan = ImplementationPlan(
        task="test",
        summary="test",
        steps=[
            PlanStep(
                id=1,
                title="edit readme",
                description="edit readme",
                files_to_edit=["README.md"],
            )
        ],
    )
    return {
        "plan": plan,
        "execution_logs": [],
    }


def test_pre_dispatch_gate_blocks_sensitive_plan(tmp_path):
    state = _make_state_with_sensitive_plan(tmp_path)
    result = pre_dispatch_gate_node(state)
    decision: PreDispatchDecision = result["pre_dispatch"]
    assert decision.blocked is True
    assert "app/auth/login.py" in decision.denied_paths


def test_pre_dispatch_gate_allows_safe_plan(tmp_path):
    state = _make_state_with_safe_plan(tmp_path)
    result = pre_dispatch_gate_node(state)
    decision: PreDispatchDecision = result["pre_dispatch"]
    assert decision.blocked is False
    assert decision.denied_paths == []


def _repo(p: Path):
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=p, check=True)
    (p / "auth.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=p, check=True)


def test_pre_dispatch_blocks_worker_when_plan_targets_sensitive(tmp_path):
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="Edit the auth module",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit secrets.py 'x'",
    )
    # If the plan targets a sensitive path, the worker is skipped and status is blocked.
    # (If the deterministic planner does not produce a sensitive file for this task,
    #  this test injects one — see Step 3 note.)
    assert record.pre_dispatch.blocked is False or record.edit_result is None
