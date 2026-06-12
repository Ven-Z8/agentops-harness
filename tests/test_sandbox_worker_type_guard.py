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


def test_sandbox_with_worker_type_blocks_honestly(tmp_path):
    # --sandbox runs the worker in-container, which only supports --worker-command.
    # A built-in worker type must be blocked with a clear message, not silently no-op.
    # The guard returns before any workspace prep, so no docker is needed.
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="add something",
        storage_path=tmp_path / "runs.db",
        worker_type="codex",
        workspace_kind="docker",
        isolation="full",
    )
    assert record.edit_result is not None
    assert record.edit_result.status == "blocked"
    assert "worker-command" in record.edit_result.stderr
    # The run status must reflect blocked, not be collapsed into "failed".
    assert record.status == "blocked"


def test_sandbox_blocked_worker_does_not_retry(tmp_path):
    # A blocked worker won't unblock on retry — even with failing validation and
    # max_attempts > 1, the loop must not re-run it.
    repo = tmp_path / "r2"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="add something",
        storage_path=tmp_path / "runs.db",
        worker_type="codex",
        workspace_kind="docker",
        isolation="full",
        test_commands=["python -c 'import sys; sys.exit(1)'"],
        max_attempts=3,
    )
    assert record.edit_result.status == "blocked"
    assert record.status == "blocked"
    assert record.attempts == 1
