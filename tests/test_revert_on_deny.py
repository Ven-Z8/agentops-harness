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


def test_denied_change_is_reverted(tmp_path):
    # Revert-on-deny is the SECOND line of defense: it catches a denied file the
    # worker wrote that the pre-dispatch gate could not predict. The path is embedded
    # in a shell string (not a standalone token), so the gate passes and the worker
    # writes secrets.py — which enforce_permissions must then revert.
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="write some config",
        storage_path=tmp_path / "runs.db",
        worker_command="sh -c 'echo leak > secrets.py'",
    )
    assert record.pre_dispatch.blocked is False  # gate did not catch it
    assert "secrets.py" in record.permission_report.enforced_reverts
    assert "secrets.py" not in record.changed_files
    assert not (repo / "secrets.py").exists()
