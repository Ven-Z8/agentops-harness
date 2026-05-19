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
        "scan_repo:complete",
        "create_plan:start",
        "create_plan:complete",
        "collect_diff:start",
        "collect_diff:complete",
        "run_tests:start",
        "run_tests:complete",
        "review_diff:start",
        "review_diff:complete",
        "assess_risk:start",
        "assess_risk:complete",
        "write_report:start",
        "write_report:complete",
        "check_report_quality:start",
        "check_report_quality:complete",
        "check_evidence:start",
        "check_evidence:complete",
    ]
    assert record.status == "completed"
