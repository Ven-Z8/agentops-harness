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

from tests.helpers_runrecord import minimal_run_record


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

    def test_solve_blocks_when_pinned_environment_unverifiable(self, tmp_path: Path) -> None:
        """AO-D03-02: a spec that pins an image digest cannot be guaranteed on a
        local workspace — fail closed before any dispatch (exit 5), no worker,
        no clone budget burned."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_with_bug(tmp_path)
        spec = _spec_json(
            "example/widgetlib",
            base,
            ["test_widget.py::test_reset_keeps_name_when_requested"],
        )
        spec["environment"] = {"image_digest": "sha256:" + "ab" * 32}
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(spec))

        dispatched: list[dict] = []

        def fail_run_harness(**kwargs):
            dispatched.append(kwargs)
            raise AssertionError(
                "run_harness must not be called when the environment is unverified"
            )

        with (
            patch.object(issues_module, "fetch_issue") as fake_fetch,
            patch("app.cli.run_harness", fail_run_harness),
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
                    "--clone-url", str(remote),
                    "--workspace-root", str(tmp_path / "workspaces"),
                ],
            )
        assert result.exit_code == 5, (
            f"expected env-block exit 5, got {result.exit_code}: {result.output}"
        )
        assert "environment" in result.output.lower()
        assert not dispatched, "worker must not dispatch when the environment is unverified"

    def test_solve_with_task_spec_pins_commit_and_composes_task(self, tmp_path: Path) -> None:
        """Happy path: the workspace is checked out at base_commit, the gate
        passes (bug present), and run_harness receives the spec's problem
        statement — never the gh issue body (the spec IS the contract).

        The fake worker actually fixes the bug, because spec mode now also
        enforces the POSITIVE contract after the run (AO-D03-01): a run that
        leaves FAIL_TO_PASS failing must not exit clean.
        """
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
            # The worker's fix lands in the workspace tree.
            (Path(kwargs["repo_path"]) / "widget.py").write_text(
                "class Widget:\n"
                "    def __init__(self, name=None):\n"
                "        self.name = name\n\n"
                "    def reset(self, keep_name=False):\n"
                "        self.name = self.name if keep_name else None\n"
            )
            record = minimal_run_record()
            record.changed_files = ["widget.py"]
            return record

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


class TestPositiveContractEnforcement:
    """AO-D03-01: after the run, the harness re-checks the task-spec contract
    on the patched tree. Execution success (worker 'completed') is NOT
    evaluation success — FAIL_TO_PASS must pass and PASS_TO_PASS must hold,
    else the run is failed and the corrected verdict is re-saved."""

    def test_solve_enforces_positive_contract_after_run(self, tmp_path: Path) -> None:
        """A worker that finishes without fixing the bug must not produce a
        completed run: the positive contract folds into record.status (failed)
        and the corrected record is persisted."""
        from app.cli import app
        from app.core import issues as issues_module
        from app.core.storage import RunStorage

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

        def fake_run_harness(**kwargs):
            # The worker reports success but leaves the tree unfixed —
            # FAIL_TO_PASS still fails on the "patched" tree.
            return minimal_run_record()

        storage_path = tmp_path / "runs.jsonl"
        with (
            patch.object(issues_module, "fetch_issue", return_value=None),
            patch("app.cli.run_harness", fake_run_harness),
            patch("app.cli.ISSUE_STORAGE_PATH", storage_path),
        ):
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

        assert result.exit_code == 4, (
            f"expected positive-contract failure exit 4, got {result.exit_code}: "
            f"{result.output}"
        )
        assert "Positive contract" in result.output
        # The corrected verdict is persisted — never a stale 'completed'.
        saved = RunStorage(storage_path).get(minimal_run_record().run_id)
        assert saved.status == "failed"
        assert any("positive_contract" in line for line in saved.execution_logs)

    def test_solve_keeps_completed_when_positive_contract_holds(self, tmp_path: Path) -> None:
        """When the worker's fix genuinely lands (FAIL_TO_PASS pass,
        PASS_TO_PASS hold), the run stays completed and exits clean."""
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

        def fake_run_harness(**kwargs):
            (Path(kwargs["repo_path"]) / "widget.py").write_text(
                "class Widget:\n"
                "    def __init__(self, name=None):\n"
                "        self.name = name\n\n"
                "    def reset(self, keep_name=False):\n"
                "        self.name = self.name if keep_name else None\n"
            )
            record = minimal_run_record()
            record.changed_files = ["widget.py"]
            return record

        storage_path = tmp_path / "runs.jsonl"
        with (
            patch.object(issues_module, "fetch_issue", return_value=None),
            patch("app.cli.run_harness", fake_run_harness),
            patch("app.cli.ISSUE_STORAGE_PATH", storage_path),
            patch.object(issues_module, "export_patch", return_value=tmp_path / "p.patch"),
            patch.object(issues_module, "commit_workspace_changes", return_value=True),
        ):
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

        assert result.exit_code == 0, result.output
        assert "Positive contract holds" in result.output


# ---------------------------------------------------------------------------
# helper shared with the gate tests
# ---------------------------------------------------------------------------


def _load_spec(path: Path):
    from app.schemas.task_spec import SweTaskSpec

    raw = json.loads(path.read_text())
    return SweTaskSpec.from_swebench_instance(raw)


# ---------------------------------------------------------------------------
# Contract preparation: test_patch + environment setup (SWE-bench-shaped
# instances carry their failing tests as a patch and need env prep).
# ---------------------------------------------------------------------------

_TESTS_PATCH = """diff --git a/test_widget.py b/test_widget.py
new file mode 100644
--- /dev/null
+++ b/test_widget.py
@@ -0,0 +1,12 @@
+from widget import Widget
+
+
+def test_reset_keeps_name_when_requested():
+    w = Widget(name='primary')
+    w.reset(keep_name=True)
+    assert w.name == 'primary'
+
+
+def test_reset_clears_name_by_default():
+    w = Widget(name='primary')
+    w.reset()
+    assert w.name is None
"""


def _make_remote_bug_untested(tmp_path: Path) -> tuple[Path, str]:
    """Bare remote with the bug but NO tests at base — the failing test only
    exists once the spec's test_patch is applied (the real-world case)."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "widget.py").write_text(
        "class Widget:\n"
        "    def __init__(self, name=None):\n"
        "        self.name = name\n\n"
        "    def reset(self, keep_name=False):\n"
        "        self.name = None\n"
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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True
    )
    return tmp_path / "remote.git", head.stdout.strip()


class TestContractPreparation:
    def _spec_with_patch(
        self, base: str, *, test_patch: str, setup: list[str] | None = None
    ) -> dict:
        raw = {
            "repo": "example/widgetlib",
            "base_commit": base,
            "problem_statement": "reset(keep_name=True) drops the configured name.",
            "FAIL_TO_PASS": json.dumps(["test_widget.py::test_reset_keeps_name_when_requested"]),
            "PASS_TO_PASS": json.dumps(["test_widget.py::test_reset_clears_name_by_default"]),
            "test_patch": test_patch,
        }
        if setup is not None:
            raw["environment"] = {"setup_commands": setup}
        return raw

    def test_solve_applies_test_patch_to_prove_bug(self, tmp_path: Path) -> None:
        """The bug exists at base but the failing test ships in the spec's
        test_patch: the harness applies it BEFORE the negative gate, proves
        the bug, dispatches, and the positive contract checks the same tree."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_bug_untested(tmp_path)
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(self._spec_with_patch(base, test_patch=_TESTS_PATCH)))

        def fake_run_harness(**kwargs):
            # The test file from the patch must be present in the workspace
            # the worker receives (prep happened before dispatch).
            assert (Path(kwargs["repo_path"]) / "test_widget.py").exists()
            (Path(kwargs["repo_path"]) / "widget.py").write_text(
                "class Widget:\n"
                "    def __init__(self, name=None):\n"
                "        self.name = name\n\n"
                "    def reset(self, keep_name=False):\n"
                "        self.name = self.name if keep_name else None\n"
            )
            record = minimal_run_record()
            record.changed_files = ["widget.py"]
            return record

        with (
            patch.object(issues_module, "fetch_issue", return_value=None),
            patch("app.cli.run_harness", fake_run_harness),
            patch.object(issues_module, "export_patch", return_value=tmp_path / "p.patch"),
            patch.object(issues_module, "commit_workspace_changes", return_value=True),
        ):
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

        assert result.exit_code == 0, result.output
        assert "Negative contract holds" in result.output
        assert "Positive contract holds" in result.output

    def test_solve_blocks_when_test_patch_fails_to_apply(self, tmp_path: Path) -> None:
        """Fail-closed: a patch that cannot apply means the spec is invalid for
        this base — block before dispatch (exit 3), never guess."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_bug_untested(tmp_path)
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(self._spec_with_patch(base, test_patch="not a patch at all"))
        )

        dispatched = []

        def fake_run_harness(**kwargs):
            dispatched.append(kwargs)
            return minimal_run_record()

        with (
            patch.object(issues_module, "fetch_issue", return_value=None),
            patch("app.cli.run_harness", fake_run_harness),
        ):
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
            f"expected patch-failure exit 3, got {result.exit_code}: {result.output}"
        )
        assert not dispatched, "worker must not dispatch when the test patch cannot apply"

    def test_solve_blocks_when_environment_setup_fails(self, tmp_path: Path) -> None:
        """Fail-closed: a declared environment that cannot be prepared is an
        unverified environment — block before the gate (exit 5)."""
        from app.cli import app
        from app.core import issues as issues_module

        remote, base = _make_remote_bug_untested(tmp_path)
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                self._spec_with_patch(
                    base,
                    test_patch=_TESTS_PATCH,
                    setup=["python -c \"raise SystemExit(1)\""],
                )
            )
        )

        dispatched = []

        def fake_run_harness(**kwargs):
            dispatched.append(kwargs)
            return minimal_run_record()

        with (
            patch.object(issues_module, "fetch_issue", return_value=None),
            patch("app.cli.run_harness", fake_run_harness),
        ):
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

        assert result.exit_code == 5, (
            f"expected env-setup failure exit 5, got {result.exit_code}: {result.output}"
        )
        assert not dispatched, "worker must not dispatch when environment setup fails"
