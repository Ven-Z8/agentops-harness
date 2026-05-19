from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app


def copy_sample_repo(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


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


def test_cli_edit_runs_external_worker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.cli.settings.llm_provider", "mock")
    repo_path = tmp_path / "sample_fastapi_app"
    copy_sample_repo(Path("examples/sample_fastapi_app"), repo_path)
    init_git_repo(repo_path)
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        "from pathlib import Path\n"
        "Path('app/cli_marker.py').write_text('MARKER = True\\n')\n"
        "print('cli worker complete')\n"
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "edit",
            "--repo",
            str(repo_path),
            "--task",
            "Create CLI marker",
            "--worker-command",
            f"{sys.executable} {worker_path}",
            "--storage",
            str(tmp_path / "runs.db"),
        ],
    )

    assert result.exit_code == 0
    assert "Mode: external worker" in result.output
    assert "app/cli_marker.py" in result.output
