import subprocess
from pathlib import Path

from app.core.graph import pre_dispatch_gate_node, run_harness
from app.schemas.governance import PreDispatchDecision
from app.schemas.plan import ImplementationPlan, PlanStep


def _plan(files: list[str]) -> ImplementationPlan:
    return ImplementationPlan(
        task="test",
        summary="test",
        steps=[PlanStep(id=1, title="x", description="x", files_to_edit=files)],
    )


def test_observe_mode_never_blocks_even_with_sensitive_plan():
    # No worker configured (observe) -> nothing to dispatch -> never blocked,
    # even if the planner's files_to_edit happens to list a sensitive/security path.
    state = {"plan": _plan(["app/auth/login.py", "tests/security/test_x.py"]), "execution_logs": []}
    decision: PreDispatchDecision = pre_dispatch_gate_node(state)["pre_dispatch"]
    assert decision.blocked is False
    assert decision.denied_paths == []


def test_blocks_when_worker_command_targets_sensitive_path():
    state = {
        "plan": _plan(["README.md"]),
        "worker_command": "agentops-scripted-edit secrets.py 'leak'",
        "execution_logs": [],
    }
    decision: PreDispatchDecision = pre_dispatch_gate_node(state)["pre_dispatch"]
    assert decision.blocked is True
    assert "secrets.py" in decision.denied_paths


def test_worker_type_alone_is_not_pre_blocked():
    # A --worker-type worker decides its own edits; pre-dispatch can't predict them.
    # It is not blocked here (post-edit revert / sandbox handle enforcement).
    state = {"plan": _plan(["app/main.py"]), "worker_type": "codex", "execution_logs": []}
    decision: PreDispatchDecision = pre_dispatch_gate_node(state)["pre_dispatch"]
    assert decision.blocked is False


def _repo(p: Path):
    p.mkdir(parents=True, exist_ok=True)
    for c in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(c, cwd=p, check=True)
    (p / "auth.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=p, check=True)


def test_run_harness_blocks_worker_command_targeting_secret(tmp_path):
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="edit a secret",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit secrets.py 'x'",
    )
    assert record.pre_dispatch.blocked is True
    assert record.edit_result is None  # worker never ran


def test_run_harness_observe_is_not_blocked(tmp_path):
    repo = tmp_path / "r2"
    _repo(repo)
    record = run_harness(repo_path=repo, task="analyze", storage_path=tmp_path / "runs.db")
    assert record.pre_dispatch.blocked is False
