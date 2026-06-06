from pathlib import Path

from app.mcp_server import (
    agentops_get_report,
    agentops_list_runs,
    agentops_run,
    agentops_scan,
    create_mcp_server,
)


def test_mcp_scan_returns_repo_profile() -> None:
    result = agentops_scan("examples/sample_fastapi_app")

    assert result["language"] == "python"
    assert result["framework"] == "fastapi"
    assert "app/main.py" in result["entrypoints"]
    assert result["repo_graph"]["summary"]["languages"] == ["python"]


def test_mcp_run_report_and_list_round_trip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.mcp_server.settings.llm_provider", "mock")
    storage_path = tmp_path / "runs.db"

    run_result = agentops_run(
        repo_path="examples/sample_fastapi_app",
        task="Add request logging middleware",
        storage_path=str(storage_path),
    )
    report_result = agentops_get_report(run_result["run_id"], storage_path=str(storage_path))
    list_result = agentops_list_runs(storage_path=str(storage_path), limit=5)

    assert run_result["status"] == "completed"
    assert run_result["risk_level"] == "low"
    assert "Risk assessment" in report_result["report"]
    assert list_result["runs"][0]["run_id"] == run_result["run_id"]


def test_create_mcp_server_has_name() -> None:
    server = create_mcp_server()

    assert server.name == "agentops-harness"
