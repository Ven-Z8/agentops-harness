import subprocess
from pathlib import Path

from app.core.git_utils import is_ephemeral_path
from app.core.graph import run_harness


def _repo(p: Path):
    p.mkdir(parents=True, exist_ok=True)
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=p, check=True)
    (p / "app.py").write_text("x=1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=p, check=True)


def test_ephemeral_path_detection():
    assert is_ephemeral_path("app/__pycache__/main.cpython-312.pyc")
    assert is_ephemeral_path("x.pyc")
    assert is_ephemeral_path(".pytest_cache/v/cache")
    assert is_ephemeral_path(".DS_Store")
    assert not is_ephemeral_path("app/main.py")
    assert not is_ephemeral_path("tests/test_x.py")


def test_pre_dispatch_blocks_worker_command_targeting_secret(tmp_path):
    repo = tmp_path / "r"
    _repo(repo)
    record = run_harness(
        repo_path=repo,
        task="touch a secret",
        storage_path=tmp_path / "runs.db",
        worker_command="agentops-scripted-edit secrets.py 'leak'",
    )
    assert record.pre_dispatch.blocked is True
    assert "secrets.py" in record.pre_dispatch.denied_paths
    assert record.edit_result is None  # worker never ran
    assert not (repo / "secrets.py").exists()  # nothing was written
