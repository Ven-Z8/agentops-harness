"""Finding A: the executor must honor the plan's tests_to_run contract.

The planner is graph-aware and may select `uv run pytest -q` for a uv project,
but if the test runner ignores that and hardcodes `python -m pytest -q`, the
plan-as-contract thesis (paper Section 3.4.2) is broken at the executor.
"""

from pathlib import Path

from app.core.graph import run_tests_node
from app.schemas.plan import ImplementationPlan, PlanStep


def make_plan(tests_to_run: list[str]) -> ImplementationPlan:
    return ImplementationPlan(
        task="demo",
        summary="demo plan",
        steps=[PlanStep(id=1, title="step", description="d")],
        acceptance_criteria=["ok"],
        tests_to_run=tests_to_run,
    )


def write_passing_test(repo: Path) -> None:
    (repo / "test_contract.py").write_text("def test_ok():\n    assert True\n")


def test_run_tests_node_executes_plan_tests_to_run(tmp_path: Path) -> None:
    write_passing_test(tmp_path)
    state = {
        "repo_path": tmp_path,
        "plan": make_plan(["python -m pytest -q -k test_ok"]),
        "execution_logs": [],
    }

    result = run_tests_node(state)

    executed = [c.command for c in result["test_results"].commands]
    assert executed == ["python -m pytest -q -k test_ok"]


def test_explicit_test_commands_override_plan(tmp_path: Path) -> None:
    write_passing_test(tmp_path)
    state = {
        "repo_path": tmp_path,
        "plan": make_plan(["python -m pytest -q -k never_runs"]),
        "test_commands": ["python -m pytest -q -k test_ok"],
        "execution_logs": [],
    }

    result = run_tests_node(state)

    executed = [c.command for c in result["test_results"].commands]
    assert executed == ["python -m pytest -q -k test_ok"]
