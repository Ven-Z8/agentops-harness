"""Task-spec → issue-solve wiring tests (Phase 2 kernel entry, slice 3).

`agentops issue solve --task-spec <file>` must:
  1. parse the spec (SWE-bench JSON or YAML with our schema);
  2. check out the workspace at spec.base_commit (pinned, never HEAD);
  3. run the negative-contract gate BEFORE any worker dispatch and
     block the run when the bug is not reproducible (fail-closed);
  4. hand the spec's problem_statement to the worker as the task contract.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner


def _spec_json(repo: str, base: str, fail_to_pass: list[str]) -> dict:
    return {
        "repo": repo,
        "base_commit": base,
        "problem_statement": "reset(keep_name=True) drops the configured name.",
        "FAIL_TO_PASS": json.dumps(fail_to_pass),
        "PASS_TO_PASS": json.dumps(["test_widget.py::test_reset_clears_name_by_default"]),
    }


def _make_remote_with_bug(tmp_path: Path) -> tuple[Path, str]:
    """Bare remote + workdir containing a real bug at a pinned commit."""
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
    for cmd in (
        ["git", "init", "-q", "--bare", str(tmp_path / "remote.git")],
    ):
        subprocess.run(cmd, check=True)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        ["git", "remote", "add", "origin", str(tmp_path / "remote.git")],
        ["git", "push", "-q", "origin", "HEAD"],
    ):
        subprocess.run(cmd, cwd=source, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True
    )
    return tmp_path / "remote.git", head.stdout.strip()


class TestTaskSpecCLIWiring:
    def test_solve_blocks_when_negative_contract_fails(self, tmp_path: Path) -> None:
        """Fail-closed: a spec whose fail_to_pass tests PASS at base must
        prevent any worker dispatch (the run budget is not burned)."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_with_bug(tmp_path)
        # Spec names a test that PASSES at base (bug not reproducible).
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                _spec_json(
                    "example/widgetlib",
                    base,
                    ["test_widget.py::test_reset_clears_name_by_default"],
                )
            )
        )

        dispatched: list[dict] = []

        def fail_run_harness(**kwargs):
            dispatched.append(kwargs)
            raise AssertionError("run_harness must not be called when the gate blocks")

        with (
            patch.object(issues_module, "fetch_issue") as fake_fetch,
            patch("app.cli.run_harness", fail_run_harness),
        ):
            fake_fetch.return_value = None  # not used under --task-spec
            result = CliRunner().invoke(
                app,
                [
                    "issue", "solve",
                    "--task-spec", str(spec_file),
                    "--owner", "example",
                    "--repo", "widgetlib",
                    "--number", "42",
                    "--worker", "codex",
                    "--clone-url", str(remote),
                    "--workspace-root", str(tmp_path / "workspaces"),
                ],
            )
        assert result.exit_code == 3, (
            f"expected gate-block exit 3, got {result.exit_code}: {result.output}"
        )
        assert "Negative contract" in result.output
        assert not dispatched, "worker must not dispatch when the gate blocks"

    def test_solve_with_task_spec_pins_commit_and_composes_task(self, tmp_path: Path) -> None:
        """Happy path: the workspace is checked out at base_commit, the gate
        passes (bug present), and run_harness receives the spec's problem
        statement — never the gh issue body (the spec IS the contract)."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_with_bug(tmp_path)
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                _spec_json(
                    "example/widgetlib",
                    base,
                    ["test_widget.py::test_reset_keeps_name_when_requested"],
                )
            )
        )

        captured: dict[str, object] = {}

        def fake_run_harness(**kwargs):
            captured.update(kwargs)
            return type("R", (), {
                "run_id": "r1", "status": "completed", "attempts": 1, "converged": True,
                "changed_files": ["widget.py"],
                "final_report": type("F", (), {"markdown": "ok"})(),
            })()

        with (
            patch.object(issues_module, "fetch_issue") as fake_fetch,
            patch("app.cli.run_harness", fake_run_harness),
            patch.object(issues_module, "export_patch", return_value=tmp_path / "p.patch"),
            patch.object(issues_module, "commit_workspace_changes", return_value=True),
        ):
            fake_fetch.return_value = None
            result = CliRunner().invoke(
                app,
                [
                    "issue", "solve",
                    "--task-spec", str(spec_file),
                    "--owner", "example",
                    "--repo", "widgetlib",
                    "--number", "42",
                    "--worker", "codex",
                    "--test-commands", "python -m pytest -q",
                    "--clone-url", str(remote),
                    "--workspace-root", str(tmp_path / "workspaces"),
                ],
            )
            assert result.exit_code == 0, result.output

        # The workspace was cloned from the spec's repo and pinned to base_commit.
        repo_path = Path(str(captured["repo_path"]))
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True
        )
        assert head.stdout.strip() == base
        # The task contract is the spec's problem statement (not the gh body).
        assert "reset(keep_name=True) drops the configured name." in str(captured["task"])
        # Negative contract ran before dispatch (recorded in the CLI output).
        assert "negative contract" in result.output.lower()


# ---------------------------------------------------------------------------
# helper shared with the gate tests
# ---------------------------------------------------------------------------


def _load_spec(path: Path):
    from app.schemas.task_spec import SweTaskSpec

    raw = json.loads(path.read_text())
    return SweTaskSpec.from_swebench_instance(raw)
