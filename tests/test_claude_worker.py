"""Tests for ClaudeCodeWorker."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.workers.claude_worker import ClaudeCodeWorker, _extract_result

# ── helpers ────────────────────────────────────────────────────────────────


def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True)
    (repo_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


# ── unit: _extract_result ──────────────────────────────────────────────────


def test_extract_result_parses_json_envelope() -> None:
    raw = json.dumps({"type": "result", "subtype": "success", "result": "Added middleware."})
    assert _extract_result(raw) == "Added middleware."


def test_extract_result_falls_back_on_plain_text() -> None:
    assert _extract_result("plain text output") == "plain text output"


def test_extract_result_handles_empty_string() -> None:
    assert _extract_result("") == ""


# ── unit: blocking conditions ──────────────────────────────────────────────


def test_worker_blocked_when_claude_not_on_path(clean_repo: Path) -> None:
    with patch("app.core.workers.claude_worker._find_claude_bin", return_value=None):
        result = ClaudeCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert result.status == "blocked"
    assert "claude" in result.stderr.lower()


def test_worker_blocked_when_repo_is_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "dirty.py").write_text("x = 1\n")  # untracked file → dirty

    with patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"):
        result = ClaudeCodeWorker().run(repo_path=repo, task="Add logging")

    assert result.status == "blocked"
    assert "dirty" in result.stderr.lower()


def test_worker_allow_dirty_bypasses_dirty_check(clean_repo: Path) -> None:
    (clean_repo / "new_file.py").write_text("x = 1\n")  # make dirty

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"result": "Done."})
    mock_proc.stderr = ""

    # Mock git checks at the git_utils level — we're testing dirty-bypass, not git ops.
    with (
        patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"),
        patch("app.core.workers.claude_worker.is_git_repo", return_value=True),
        patch("app.core.workers.claude_worker.collect_status_lines", return_value=["M dirty.py"]),
        patch("app.core.workers.claude_worker.subprocess.run", return_value=mock_proc),
    ):
        result = ClaudeCodeWorker().run(repo_path=clean_repo, task="Add logging", allow_dirty=True)

    assert result.status == "completed"


# ── unit: subprocess success / failure ────────────────────────────────────


def test_worker_returns_completed_on_exit_0(clean_repo: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"result": "Added request logging middleware."})
    mock_proc.stderr = ""

    with (
        patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"),
        patch("app.core.workers.claude_worker.is_git_repo", return_value=True),
        patch("app.core.workers.claude_worker.collect_status_lines", return_value=[]),
        patch("app.core.workers.claude_worker.subprocess.run", return_value=mock_proc),
    ):
        result = ClaudeCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert result.status == "completed"
    assert result.exit_code == 0
    assert "Added request logging" in result.stdout


def test_worker_returns_failed_on_nonzero_exit(clean_repo: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "claude exited with error"

    with (
        patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"),
        patch("app.core.workers.claude_worker.is_git_repo", return_value=True),
        patch("app.core.workers.claude_worker.collect_status_lines", return_value=[]),
        patch("app.core.workers.claude_worker.subprocess.run", return_value=mock_proc),
    ):
        result = ClaudeCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert result.status == "failed"
    assert result.exit_code == 1


def test_worker_returns_failed_on_timeout(clean_repo: Path) -> None:
    with (
        patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"),
        patch("app.core.workers.claude_worker.is_git_repo", return_value=True),
        patch("app.core.workers.claude_worker.collect_status_lines", return_value=[]),
        patch(
            "app.core.workers.claude_worker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5),
        ),
    ):
        result = ClaudeCodeWorker().run(
            repo_path=clean_repo,
            task="Add logging",
            timeout_seconds=5,
        )

    assert result.status == "failed"
    assert result.exit_code is None
    assert "timed out" in result.stderr.lower()


# ── unit: env var injection ────────────────────────────────────────────────


def test_subprocess_env_includes_claudecode_key(clean_repo: Path) -> None:
    """CLAUDECODE="" must be in the subprocess env to allow nested sessions."""
    captured_env: dict[str, str] = {}

    def capture_run(argv: list[str], **kwargs: object) -> MagicMock:
        captured_env.update(kwargs.get("env", {}))  # type: ignore[arg-type]
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = json.dumps({"result": "ok"})
        mock.stderr = ""
        return mock

    with (
        patch("app.core.workers.claude_worker._find_claude_bin", return_value="/usr/bin/claude"),
        patch("app.core.workers.claude_worker.is_git_repo", return_value=True),
        patch("app.core.workers.claude_worker.collect_status_lines", return_value=[]),
        patch("app.core.workers.claude_worker.subprocess.run", side_effect=capture_run),
    ):
        ClaudeCodeWorker().run(repo_path=clean_repo, task="task")

    assert "CLAUDECODE" in captured_env
