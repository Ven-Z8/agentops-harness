from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.agents.repo_scanner import RepoScanner
from app.core.config import settings
from app.core.graph import run_harness
from app.core.llm import build_runtime_llm_client
from app.core.storage import RunStorage


def _storage_path(storage_path: str | None) -> Path:
    return Path(storage_path) if storage_path else settings.run_storage


def agentops_scan(repo_path: str) -> dict[str, Any]:
    """Profile a local repository for language, framework, tests, and entrypoints."""
    profile = RepoScanner().scan(Path(repo_path))
    return profile.model_dump(mode="json")


def agentops_run(
    repo_path: str,
    task: str,
    storage_path: str | None = None,
) -> dict[str, Any]:
    """Run the AgentOps Harness workflow and persist a run record."""
    record = run_harness(
        repo_path=Path(repo_path),
        task=task,
        storage_path=_storage_path(storage_path),
        llm_client=build_runtime_llm_client(settings),
    )
    return {
        "run_id": record.run_id,
        "status": record.status,
        "risk_score": record.risk_report.risk_score,
        "risk_level": record.risk_report.risk_level,
        "tests_passed": record.test_results.passed,
        "report": record.final_report.markdown,
    }


def agentops_get_report(run_id: str, storage_path: str | None = None) -> dict[str, str]:
    """Fetch a saved AgentOps Harness PR-style report."""
    record = RunStorage(_storage_path(storage_path)).get(run_id)
    return {"run_id": record.run_id, "report": record.final_report.markdown}


def agentops_list_runs(storage_path: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List recent AgentOps Harness runs."""
    records = RunStorage(_storage_path(storage_path)).list(limit=limit)
    return {
        "runs": [
            {
                "run_id": record.run_id,
                "task": record.task,
                "status": record.status,
                "risk_score": record.risk_report.risk_score,
                "risk_level": record.risk_report.risk_level,
                "completed_at": record.completed_at.isoformat(),
            }
            for record in records
        ]
    }


def create_mcp_server() -> FastMCP:
    mcp = FastMCP("agentops-harness")
    mcp.tool()(agentops_scan)
    mcp.tool()(agentops_run)
    mcp.tool()(agentops_get_report)
    mcp.tool()(agentops_list_runs)
    return mcp


def main() -> None:
    create_mcp_server().run()


if __name__ == "__main__":
    main()
