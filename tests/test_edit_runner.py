from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.edit_runner import ExternalWorkerRunner, render_worker_command


def init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def test_render_worker_command_preserves_task_as_single_argument(tmp_path: Path) -> None:
    argv = render_worker_command(
        f"{sys.executable} {tmp_path / 'worker.py'} --repo {{repo_path}} --task {{task}}",
        repo_path=tmp_path,
        task="Create request logging middleware",
    )

    assert argv[-2:] == ["--task", "Create request logging middleware"]
    assert argv[-4:-2] == ["--repo", str(tmp_path)]


def test_render_worker_command_rejects_destructive_template(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Blocked potentially destructive command"):
        render_worker_command("rm -rf {repo_path}", repo_path=tmp_path, task="bad idea")


def test_external_worker_blocks_dirty_repo_by_default(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "app.py").write_text("print('hello')\n")
    init_git_repo(repo_path)
    (repo_path / "dirty.py").write_text("dirty = True\n")

    result = ExternalWorkerRunner().run(
        repo_path=repo_path,
        task="Create marker",
        command_template=f"{sys.executable} -c \"print('should not run')\"",
    )

    assert result.status == "blocked"
    assert result.exit_code is None
    assert "dirty" in result.stderr.lower()


def test_external_worker_runs_explicit_command_and_captures_output(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "app.py").write_text("print('hello')\n")
    init_git_repo(repo_path)

    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        "from pathlib import Path\n"
        "Path('marker.txt').write_text('created by worker\\n')\n"
        "print('worker complete')\n"
    )

    result = ExternalWorkerRunner().run(
        repo_path=repo_path,
        task="Create marker",
        command_template=f"{sys.executable} {worker_path}",
    )

    assert result.status == "completed"
    assert result.exit_code == 0
    assert "worker complete" in result.stdout
    assert (repo_path / "marker.txt").read_text() == "created by worker\n"
