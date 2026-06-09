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
        if {".git", "__pycache__", ".pytest_cache"}.intersection(relative.parts):
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


def test_cli_plan_is_graph_aware() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "plan",
            "--repo",
            "examples/sample_fastapi_app",
            "--task",
            "Add a /healthz endpoint",
        ],
    )

    assert result.exit_code == 0
    # uv repo (pyproject + uv.lock) -> graph-aware validation commands, not the
    # profile-only "python -m pytest -q" fallback.
    assert "uv run pytest -q" in result.output
    assert "uv run ruff check ." in result.output
    assert "app/main.py" in result.output


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


def test_cli_artifacts_path_and_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.cli.settings.llm_provider", "mock")
    repo_path = tmp_path / "sample_fastapi_app"
    copy_sample_repo(Path("examples/sample_fastapi_app"), repo_path)
    init_git_repo(repo_path)
    storage_path = tmp_path / "runs.db"
    runner = CliRunner()

    run_result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(repo_path),
            "--task",
            "Analyze request logging",
            "--storage",
            str(storage_path),
        ],
    )

    assert run_result.exit_code == 0
    run_id = next((part for part in run_result.output.split() if len(part) == 32), "")
    assert run_id

    path_result = runner.invoke(
        app,
        [
            "artifacts",
            "path",
            "--run-id",
            run_id,
            "--storage",
            str(storage_path),
        ],
    )
    assert path_result.exit_code == 0
    artifact_dir = storage_path.parent / "runs" / run_id
    assert str(artifact_dir) in path_result.output

    output_file = tmp_path / "bundle.zip"
    export_result = runner.invoke(
        app,
        [
            "artifacts",
            "export",
            "--run-id",
            run_id,
            "--storage",
            str(storage_path),
            "--output",
            str(output_file),
        ],
    )
    assert export_result.exit_code == 0
    assert output_file.exists()
