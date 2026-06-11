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
        "pre_dispatch:ok",
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
