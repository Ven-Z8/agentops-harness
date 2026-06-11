import subprocess
from pathlib import Path

from app.core.graph import run_harness


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_scripted_worker_edits_without_a_model_call(tmp_path: Path):
    repo = tmp_path / "r"
    _git_repo(repo)
    record = run_harness(
        repo_path=repo,
        task="add a NOTES.md file",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit NOTES.md 'scripted by harness'",
    )
    assert record.edit_result is not None
    assert record.edit_result.status == "completed"
    assert "NOTES.md" in record.changed_files
