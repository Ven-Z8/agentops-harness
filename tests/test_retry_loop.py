import subprocess

from app.core.graph import run_harness


def _repo(p):
    p.mkdir(parents=True, exist_ok=True)
    for c in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(c, cwd=p, check=True)
    (p / "app.py").write_text("x=1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=p, check=True)


def test_loop_retries_to_max_on_failing_validation(tmp_path):
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="add notes",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit NOTES.md 'note'",
        test_commands=["python -c 'import sys; sys.exit(1)'"],  # always fails
        max_attempts=2,
    )
    assert record.attempts == 2
    assert record.converged is False


def test_loop_stops_at_one_when_validation_passes(tmp_path):
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="add notes",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit NOTES.md 'note'",
        test_commands=["python -c 'print(0)'"],  # passes
        max_attempts=3,
    )
    assert record.attempts == 1
    assert record.converged is True
