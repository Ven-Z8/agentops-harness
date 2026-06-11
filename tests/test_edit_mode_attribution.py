"""Track-1 hardening: prove edit-mode attribution end-to-end.

Edit mode requires a clean git repo so every changed file is attributable to the
worker command. This drives a real worker command against a fresh git repo and
asserts the file it created shows up as a changed file on the run record.
"""

import subprocess
from pathlib import Path

from app.core.graph import run_harness


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "app.py").write_text("def f():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_edit_mode_attributes_worker_created_file(tmp_path: Path):
    repo = tmp_path / "clean_repo"
    _init_repo(repo)
    # Sanity: the repo starts clean, so any change is the worker's.
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout.strip() == ""

    record = run_harness(
        repo_path=repo,
        task="add a healthz module",
        storage_path=tmp_path / "runs.db",
        worker_command="bash -c 'echo \"def healthz(): return 200\" > healthz.py'",
    )

    assert record.edit_result is not None
    assert record.edit_result.status == "completed"
    assert "healthz.py" in record.changed_files


def test_edit_mode_blocks_on_dirty_repo(tmp_path: Path):
    repo = tmp_path / "dirty_repo"
    _init_repo(repo)
    (repo / "app.py").write_text("def f():\n    return 2\n")  # pre-existing dirt

    record = run_harness(
        repo_path=repo,
        task="add a healthz module",
        storage_path=tmp_path / "runs.db",
        worker_command="bash -c 'echo x > healthz.py'",
    )

    # The worker must be blocked so changes are not misattributed.
    assert record.edit_result is not None
    assert record.edit_result.status == "blocked"
