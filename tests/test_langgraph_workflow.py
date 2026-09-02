from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.core.graph import build_workflow_graph, run_harness


def test_build_workflow_graph_returns_compiled_langgraph() -> None:
    graph = build_workflow_graph()

    assert isinstance(graph, CompiledStateGraph)


def test_langgraph_run_records_node_trace(tmp_path: Path) -> None:
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=tmp_path / "runs.db",
    )

    assert record.execution_logs == [
        "scan_repo:start",
        "repo_graph:complete",
        "goal_model:absent",
        "scan_repo:complete",
        "recall_experience:start",
        "recall_experience:miss",
        "create_plan:start",
        "create_plan:complete",
        "prepare_workspace:start",
        "prepare_workspace:complete",
        "pre_dispatch:observe",
        "collect_diff:start",
        "collect_diff:complete",
        "enforce_permissions:skip",
        "run_tests:start",
        "run_tests:complete",
        "check_convergence:skip",
        "build_changed_subgraph:start",
        "build_changed_subgraph:complete",
        "review_diff:start",
        "review_diff:complete",
        "assess_risk:start",
        "assess_risk:complete",
        "classify_permissions:start",
        "classify_permissions:complete",
        "write_report:start",
        "write_report:complete",
        "check_report_quality:start",
        "check_report_quality:complete",
        "check_evidence:start",
        "check_evidence:complete",
        "build_product_review:start",
        "build_product_review:complete",
        "assemble_verification:start",
        "assemble_verification:complete",
        "audit_conflicts:start",
        "audit_conflicts:complete",
    ]
    assert record.repo_graph is not None
    assert record.repo_graph.summary.languages == ["python"]
    assert record.status == "completed"


def test_langgraph_plan_is_graph_aware(tmp_path: Path) -> None:
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=tmp_path / "runs.db",
    )

    # No LLM client -> deterministic graph-aware planner. uv commands prove the
    # repo_graph flowed from scan_repo_node into create_plan_node.
    assert "uv run pytest -q" in record.plan.tests_to_run
    inspected = {path for step in record.plan.steps for path in step.files_to_inspect}
    assert "app/main.py" in inspected


def test_required_test_failure_cannot_complete_or_converge(tmp_path: Path) -> None:
    """AO-D01-02: failed required validation must not report success.

    A worker that exits cleanly but leaves the repository's required tests
    failing cannot produce a ``completed`` run or a converged loop — execution
    success and evaluation success are separate concerns, and evaluation
    failure must dominate the terminal status.
    """
    import subprocess

    repo = tmp_path / "victim"
    repo.mkdir()
    (repo / "app.py").write_text("def broken(:\n")
    (repo / "test_app.py").write_text("def test_x():\n    import app\n    assert False\n")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True)

    record = run_harness(
        repo_path=repo,
        task="Make the code work",
        storage_path=tmp_path / "runs.db",
        worker_command="touch modified_marker.txt",
        max_attempts=1,
    )

    # Execution succeeded (worker exit 0)…
    assert record.edit_result is not None
    assert record.edit_result.status == "completed"
    # …but the required validation failed: the run must not be completed or converged.
    assert record.test_results.passed is False
    assert record.status != "completed"
    assert record.converged is False


def test_unknown_worker_type_fails_closed(tmp_path: Path) -> None:
    """AO-D01-03: an unknown worker type must block the run, not skip silently.

    A typo in --worker-type previously fell through the dispatch chain to the
    "no worker" branch: no worker ran, no error surfaced, and the run was
    still reported completed. Unknown kinds must fail closed with a clear,
    persisted reason.
    """
    import subprocess

    repo = tmp_path / "victim"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True)

    record = run_harness(
        repo_path=repo,
        task="Do something",
        storage_path=tmp_path / "runs.db",
        worker_type="banana",
        max_attempts=1,
    )

    # Fail closed: a worker was requested but none could run.
    assert record.status == "blocked"
    assert record.edit_result is not None
    assert record.edit_result.status == "blocked"
    assert "banana" in (record.edit_result.stderr or "")
