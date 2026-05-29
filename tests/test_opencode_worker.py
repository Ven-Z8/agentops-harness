"""Tests for OpenCodeWorker."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.workers.opencode_worker import OpenCodeWorker


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


def test_worker_blocked_when_opencode_not_on_path(clean_repo: Path) -> None:
    with patch("app.core.workers.opencode_worker._find_opencode_bin", return_value=None):
        result = OpenCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert result.status == "blocked"
    assert "opencode" in result.stderr.lower()


def test_worker_returns_completed_on_exit_0(clean_repo: Path) -> None:
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "OpenCode changed the files."
    mock_proc.stderr = ""

    with (
        patch(
            "app.core.workers.opencode_worker._find_opencode_bin",
            return_value="/usr/bin/opencode",
        ),
        patch("app.core.workers.opencode_worker.is_git_repo", return_value=True),
        patch("app.core.workers.opencode_worker.collect_status_lines", return_value=[]),
        patch("app.core.workers.opencode_worker.subprocess.run", return_value=mock_proc),
    ):
        result = OpenCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert result.status == "completed"
    assert result.exit_code == 0
    assert "OpenCode changed" in result.stdout


def test_worker_adds_model_flag_when_opencode_model_is_set(
    clean_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_argv: list[str] = []
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "ok"
    mock_proc.stderr = ""
    monkeypatch.setenv("OPENCODE_MODEL", "openrouter/moonshotai/kimi-k2")

    def capture_run(argv: list[str], **kwargs: object) -> MagicMock:
        captured_argv.extend(argv)
        return mock_proc

    with (
        patch(
            "app.core.workers.opencode_worker._find_opencode_bin",
            return_value="/usr/bin/opencode",
        ),
        patch("app.core.workers.opencode_worker.is_git_repo", return_value=True),
        patch("app.core.workers.opencode_worker.collect_status_lines", return_value=[]),
        patch("app.core.workers.opencode_worker.subprocess.run", side_effect=capture_run),
    ):
        OpenCodeWorker().run(repo_path=clean_repo, task="Add logging")

    assert "--model" in captured_argv
    assert "openrouter/moonshotai/kimi-k2" in captured_argv


def test_worker_returns_failed_on_timeout(clean_repo: Path) -> None:
    with (
        patch(
            "app.core.workers.opencode_worker._find_opencode_bin",
            return_value="/usr/bin/opencode",
        ),
        patch("app.core.workers.opencode_worker.is_git_repo", return_value=True),
        patch("app.core.workers.opencode_worker.collect_status_lines", return_value=[]),
        patch(
            "app.core.workers.opencode_worker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="opencode", timeout=5),
        ),
    ):
        result = OpenCodeWorker().run(
            repo_path=clean_repo,
            task="Add logging",
            timeout_seconds=5,
        )

    assert result.status == "failed"
    assert result.exit_code is None
    assert "timed out" in result.stderr.lower()
