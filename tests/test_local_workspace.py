import subprocess
from pathlib import Path

from app.core.workspace.local import LocalWorkspace


def _repo(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=p, check=True)
    (p / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)


def test_local_prepare_is_ok_noop(tmp_path: Path):
    _repo(tmp_path)
    assert LocalWorkspace(tmp_path).prepare().ok is True


def test_local_run_executes_in_repo(tmp_path: Path):
    _repo(tmp_path)
    result = LocalWorkspace(tmp_path).run(["python", "-c", "print('hi')"], timeout_seconds=30)
    assert result.exit_code == 0
    assert "hi" in result.stdout


def test_local_read_changes_untracked_file_in_changed_list(tmp_path: Path):
    # An untracked file shows in the changed-files list (git status) but NOT in the
    # diff summary/body (git diff ignores untracked) — characterizing today's behavior.
    _repo(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n")
    changed, summary, body = LocalWorkspace(tmp_path).read_changes()
    assert "b.py" in changed
    assert "b.py" not in body


def test_local_read_changes_modified_tracked_file(tmp_path: Path):
    # A modified tracked file appears in the changed list, the --stat summary, and
    # the diff body — exactly as the underlying git_utils functions report today.
    _repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 99\n")
    changed, summary, body = LocalWorkspace(tmp_path).read_changes()
    assert "a.py" in changed
    assert "a.py" in summary
    assert "99" in body
