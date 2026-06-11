"""Task 3 tests: run_tests_node and collect_diff_node route through workspace."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.schemas.test import CommandResult
from app.schemas.workspace import PrepareResult


def _make_fake_workspace(
    run_return: CommandResult | None = None,
    read_changes_return: tuple | None = None,
):
    """Return a fake Workspace that records calls."""
    ws = MagicMock()
    ws.run.return_value = run_return or CommandResult(
        command="uv run pytest -q",
        exit_code=0,
        duration_seconds=0.1,
        stdout="1 passed",
        stderr="",
    )
    ws.read_changes.return_value = read_changes_return or (
        ["app/main.py"],
        "1 file changed, 3 insertions(+)",
        "diff --git a/app/main.py...",
    )
    ws.prepare.return_value = PrepareResult(ok=True)
    return ws


def test_collect_diff_node_uses_workspace_read_changes():
    """collect_diff_node must call state['workspace'].read_changes()."""
    from app.core.graph import collect_diff_node

    fake_ws = _make_fake_workspace()
    state = {
        "repo_path": Path("examples/sample_fastapi_app"),
        "workspace": fake_ws,
        "workspace_report": PrepareResult(ok=True),
        "execution_logs": [],
    }
    result = collect_diff_node(state)
    fake_ws.read_changes.assert_called_once()
    assert result["changed_files"] == ["app/main.py"]
    assert "1 file changed" in result["diff_summary"]
    assert "collect_diff:complete" in result["execution_logs"]


def test_collect_diff_node_falls_back_without_workspace():
    """When no workspace in state, collect_diff_node still works (backward compat)."""
    from app.core.graph import collect_diff_node

    state = {
        "repo_path": Path("examples/sample_fastapi_app"),
        "execution_logs": [],
    }
    # Should not raise — uses git_utils directly
    result = collect_diff_node(state)
    assert "changed_files" in result
    assert "collect_diff:complete" in result["execution_logs"]
