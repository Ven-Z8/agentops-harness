from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.graph import run_harness
from app.core.storage import SQLiteRunStorage


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


def test_run_harness_edit_mode_records_worker_diff(tmp_path: Path) -> None:
    repo_path = tmp_path / "sample_fastapi_app"
    copy_sample_repo(Path("examples/sample_fastapi_app"), repo_path)
    init_git_repo(repo_path)
    storage_path = tmp_path / "runs.db"
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        "from pathlib import Path\n"
        "Path('app/worker_marker.py').write_text('MARKER = True\\n')\n"
        "print('worker wrote marker')\n"
    )

    record = run_harness(
        repo_path=repo_path,
        task="Create marker module",
        storage_path=storage_path,
        test_commands=["python -m pytest -q"],
        worker_command=f"{sys.executable} {worker_path}",
    )

    fetched = SQLiteRunStorage(storage_path).get(record.run_id)

    assert record.status == "completed"
    assert record.edit_result is not None
    assert record.edit_result.status == "completed"
    assert "app/worker_marker.py" in record.changed_files
    assert record.execution_logs[6:8] == [
        "run_external_worker:start",
        "run_external_worker:complete",
    ]
    assert fetched.edit_result is not None
    assert fetched.edit_result.stdout.strip() == "worker wrote marker"
