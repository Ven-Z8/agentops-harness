"""Task 2 + Task 4 tests for the prepare_workspace node."""
from __future__ import annotations

from pathlib import Path

from app.core.graph import run_harness
from app.schemas.workspace import PrepareResult

# ---------------------------------------------------------------------------
# Task 2: prepare_workspace node wires up and stores PrepareResult in record
# ---------------------------------------------------------------------------

def test_run_harness_workspace_report_ok(tmp_path: Path) -> None:
    """LocalWorkspace.prepare() is a no-op that returns ok=True."""
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=tmp_path / "runs.db",
    )
    assert record.workspace_report.ok is True


def test_run_harness_workspace_report_written_to_artifact(tmp_path: Path) -> None:
    """workspace_report.json must be written to the artifact directory."""
    import json

    storage_path = tmp_path / "runs.db"
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=storage_path,
    )
    artifact_dir = storage_path.parent / "runs" / record.run_id
    ws_file = artifact_dir / "workspace_report.json"
    assert ws_file.exists(), f"workspace_report.json not found in {artifact_dir}"
    data = json.loads(ws_file.read_text())
    assert data["ok"] is True


def test_run_harness_trace_includes_prepare_workspace(tmp_path: Path) -> None:
    """Execution logs must include prepare_workspace entries."""
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=tmp_path / "runs.db",
    )
    assert "prepare_workspace:start" in record.execution_logs
    assert "prepare_workspace:complete" in record.execution_logs


# ---------------------------------------------------------------------------
# Task 4: skip worker when workspace_report.ok is False
# ---------------------------------------------------------------------------

def test_run_external_worker_node_skipped_when_workspace_not_ready() -> None:
    """If workspace_report.ok is False, worker is skipped and logs contain marker."""
    from app.core.graph import run_external_worker_node

    fake_state = {
        "workspace_report": PrepareResult(ok=False, diagnostic="env broken"),
        "execution_logs": ["prepare_workspace:start", "workspace_blocked"],
        "worker_type": None,
        "worker_command": None,
        "worker_timeout_seconds": 300,
        "allow_dirty": False,
    }
    result = run_external_worker_node(fake_state)
    assert result["edit_result"] is None
    assert "worker_skipped:workspace_not_ready" in result["execution_logs"]
