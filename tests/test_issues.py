"""Governed GitHub-issue run path tests (AO-14D flagship).

Unit tests are hermetic (mock gh; local fixture repos). The live issue demo is
a separate, explicitly-networked smoke path, not part of the default suite.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.issues import (
    GitHubIssue,
    IssueError,
    compose_worker_command,
    fetch_issue,
    prepare_issue_workspace,
)


def _fixture_issue(**overrides) -> GitHubIssue:
    defaults = dict(
        owner="example",
        repo="widgetlib",
        number=42,
        title="Widget.reset() drops configured name",
        body="Resetting a widget clears its `name` even when `keep_name=True`.\n\n"
        "Steps:\n1. create widget with name\n2. call reset(keep_name=True)\n\n"
        "Expected: name preserved. Actual: name is None.",
        labels=("bug",),
        state="open",
        html_url="https://github.com/example/widgetlib/issues/42",
    )
    defaults.update(overrides)
    return GitHubIssue(**defaults)


def test_compose_task_contains_issue_and_scope() -> None:
    issue = _fixture_issue()
    task = issue.compose_task()

    assert issue.slug in task
    assert issue.title in task
    assert "keep_name=True" in task
    assert issue.html_url in task
    assert "bug" in task
    assert "smallest change" in task
    # A composed task must not be empty or trivially short.
    assert len(task) > 200


def test_compose_task_truncates_huge_bodies() -> None:
    issue = _fixture_issue(body="x" * 10_000)
    task = issue.compose_task(max_body_chars=1000)

    assert len(task) < 2000
    assert "truncated" in task


def test_fetch_issue_parses_gh_json() -> None:
    payload = json.dumps(
        {
            "number": 7,
            "title": "Fix the thing",
            "body": "The thing is broken.",
            "labels": [{"name": "bug"}, {"name": "good first issue"}],
            "state": "open",
            "url": "https://github.com/example/widgetlib/issues/7",
        }
    )

    def fake_run_gh(args, timeout=60):
        if "comments" in args[-1]:
            comments = [{"author": {"login": "dev"}, "body": "Repro confirmed."}]
            return json.dumps({"comments": comments})
        return payload

    with patch("app.core.issues._run_gh", side_effect=fake_run_gh):
        issue = fetch_issue("example", "widgetlib", 7)

    assert issue.number == 7
    assert issue.title == "Fix the thing"
    assert issue.labels == ("bug", "good first issue")
    assert "Repro confirmed." in issue.body


def test_fetch_issue_survives_comment_failure() -> None:
    payload = json.dumps(
        {
            "number": 8,
            "title": "T",
            "body": "B",
            "labels": [],
            "state": "open",
            "url": "https://github.com/example/widgetlib/issues/8",
        }
    )

    def fake_run_gh(args, timeout=60):
        if "comments" in args[-1]:
            raise IssueError("comment endpoint exploded")
        return payload

    with patch("app.core.issues._run_gh", side_effect=fake_run_gh):
        issue = fetch_issue("example", "widgetlib", 8)

    # Enrichment failure is recorded, not fatal.
    assert "comment fetch failed" in issue.body


def test_fetch_issue_raises_on_gh_failure() -> None:
    def fake_run_gh(args, timeout=60):
        raise IssueError("gh issue view … failed: not found")

    with (
        patch("app.core.issues._run_gh", side_effect=fake_run_gh),
        pytest.raises(IssueError),
    ):
        fetch_issue("example", "widgetlib", 999)


def test_prepare_issue_workspace_rejects_existing_directory(tmp_path: Path) -> None:
    existing = tmp_path / "widgetlib-42"
    existing.mkdir()

    with pytest.raises(IssueError, match="already exists"):
        prepare_issue_workspace(_fixture_issue(), tmp_path)


def _make_remote_fixture(tmp_path: Path) -> Path:
    """A tiny bare 'remote' with a real bug the worker script can fix."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "widget.py").write_text(
        "class Widget:\n"
        "    def __init__(self, name=None):\n"
        "        self.name = name\n\n"
        "    def reset(self, keep_name=False):\n"
        "        self.name = None\n"
    )
    (source / "test_widget.py").write_text(
        "from widget import Widget\n\n\n"
        "def test_reset_keeps_name_when_requested():\n"
        "    w = Widget(name='primary')\n"
        "    w.reset(keep_name=True)\n"
        "    assert w.name == 'primary'\n\n\n"
        "def test_reset_clears_name_by_default():\n"
        "    w = Widget(name='primary')\n"
        "    w.reset()\n"
        "    assert w.name is None\n"
    )
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "remote.git")], check=True)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "remote.git")],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=source, check=True)
    return tmp_path / "remote.git"


def test_prepare_issue_workspace_clones_and_branches(tmp_path: Path) -> None:
    remote = _make_remote_fixture(tmp_path)
    issue = _fixture_issue()

    repo_path, branch = prepare_issue_workspace(
        issue, tmp_path / "work", clone_url=str(remote)
    )

    assert branch == f"agentops/issue-{issue.number}"
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert current.stdout.strip() == branch
    assert (repo_path / "widget.py").exists()


def test_worker_command_template_for_issue(tmp_path: Path) -> None:
    """The worker command for an issue run is concrete and executable."""
    issue = _fixture_issue()
    cmd = compose_worker_command("codex", repo_path=tmp_path, task=issue.compose_task())

    assert cmd.startswith("codex")
    assert "-s workspace-write" in cmd
    # The task must be passed as a single quoted argument (no shell re-parsing).
    assert "Resolve GitHub issue" in cmd


def test_governed_issue_run_end_to_end(tmp_path: Path) -> None:
    """The flagship path, hermetically: issue → clone → governed worker → patch.

    A scripted (deterministic, no-model) worker plays the coding agent: given
    the composed issue task, it applies the fix the issue describes. The
    harness must then govern that run — validate the fix against the repo's
    tests, block nothing (the change is in scope), and produce a patch whose
    content actually resolves the issue. This is the entire thesis in one
    test: the harness governs a worker on a real issue-shaped problem.
    """
    from app.core.graph import run_harness
    from app.core.issues import commit_workspace_changes, export_patch

    remote = _make_remote_fixture(tmp_path)
    issue = _fixture_issue()
    repo_path, branch = prepare_issue_workspace(
        issue, tmp_path / "work", clone_url=str(remote)
    )

    # The "worker": a deterministic script that applies the fix the issue asks
    # for (respect keep_name) — standing in for codex/claude with zero API cost.
    worker_script = tmp_path / "fix_worker.py"
    worker_script.write_text(
        "from pathlib import Path\n"
        "p = Path('widget.py')\n"
        "src = p.read_text()\n"
        "fixed = src.replace(\n"
        "    \"    def reset(self, keep_name=False):\\n        self.name = None\\n\",\n"
        "    \"    def reset(self, keep_name=False):\\n\"\n"
        "    \"        if not keep_name:\\n            self.name = None\\n\",\n"
        ")\n"
        "p.write_text(fixed)\n"
    )

    record = run_harness(
        repo_path=repo_path,
        task=issue.compose_task(),
        storage_path=tmp_path / "runs.db",
        worker_command=f"python {worker_script}",
        test_commands=["python -m pytest -q"],
        max_attempts=1,
    )

    # The governed outcome: execution + evaluation both succeeded honestly.
    assert record.edit_result is not None
    assert record.edit_result.status == "completed"
    assert record.test_results.passed, [
        (c.command, c.exit_code, c.stderr[-300:]) for c in record.test_results.commands
    ]
    assert record.status == "completed"
    assert "widget.py" in record.changed_files

    # And the evidence bundle exists for another engineer to inspect.
    artifact_dir = tmp_path / "runs" / record.run_id
    assert (artifact_dir / "run_record.json").exists()

    # Export the patch FIRST (working-tree diff vs HEAD); committing closes the
    # diff-vs-HEAD window, so commit afterwards for the branch to remain clean.
    patch_file = export_patch(repo_path, tmp_path / "issue-42.patch")
    patch_text = patch_file.read_text()
    assert "keep_name" in patch_text

    committed = commit_workspace_changes(repo_path, f"fix: {issue.slug}")
    assert committed
    assert "agentops/issue-42" in subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    ).stdout


def test_governed_issue_run_fails_closed_on_bad_worker(tmp_path: Path) -> None:
    """The same path, but the 'worker' breaks the code: governance must say so.

    A worker that exits 0 while leaving required validation red cannot report
    a completed run — the AO-D01-02 invariant, exercised on the issue path.
    """
    from app.core.graph import run_harness

    remote = _make_remote_fixture(tmp_path)
    issue = _fixture_issue()
    repo_path, _ = prepare_issue_workspace(issue, tmp_path / "work", clone_url=str(remote))

    bad_worker = tmp_path / "bad_worker.py"
    bad_worker.write_text(
        "from pathlib import Path\n"
        "p = Path('widget.py')\n"
        "p.write_text('def broken(:')\n"  # exits 0, leaves broken code
    )

    record = run_harness(
        repo_path=repo_path,
        task=issue.compose_task(),
        storage_path=tmp_path / "runs.db",
        worker_command=f"python {bad_worker}",
        test_commands=["python -m pytest -q"],
        max_attempts=1,
    )

    assert record.edit_result is not None
    assert record.edit_result.status == "completed"  # the process ran fine…
    assert record.test_results.passed is False      # …but the evaluation failed
    assert record.status == "failed"                 # …so the run is failed, not completed
