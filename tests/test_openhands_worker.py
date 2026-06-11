import subprocess
import sys
from pathlib import Path

from app.core.workers.openhands_worker import OpenHandsWorker


def test_blocks_on_non_git_repo(tmp_path: Path):
    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)
    assert result.status == "blocked"
    assert "git repository" in result.stderr


def test_blocks_on_dirty_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.py").write_text("x=1\n")  # untracked -> dirty
    result = OpenHandsWorker().run(repo_path=tmp_path, task="x", timeout_seconds=5)
    assert result.status == "blocked"
    assert "dirty" in result.stderr.lower()


def test_runner_exits_2_without_a_task():
    # The runner reads the task from stdin; an empty task is a usage error (exit 2),
    # reached before any SDK import or auth — so this needs neither.
    completed = subprocess.run(
        [sys.executable, "-m", "app.core.workers.openhands_runner", "."],
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2
