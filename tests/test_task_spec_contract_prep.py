"""Contract preparation before gating: test_patch + environment setup.

Real SWE-bench-style instances carry their failing tests as a *test patch*
(the tests often do not exist at base_commit), and real repos need a
prepared environment before pytest can run at all (e.g. `uv sync`). Both
belong to the deterministic preparation half of the contract: they run
AFTER the clone at base_commit and BEFORE the negative-contract gate,
fail-closed, and never fabricate evidence.

Probe isolation: contract probes run with `-o addopts=` so a repo's global
pytest add-ons (coverage floors, etc.) cannot turn a passing test into a
failing command — dmr's own test-command uses the same trick. When the
clone carries a repo-local `.venv`, probes use it instead of the harness
interpreter (the target's dependencies are the target's business).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.task_spec_gate import (
    EnvironmentSetupError,
    TestPatchError,
    _pytest_command_for,
    apply_test_patch,
    run_environment_setup,
)
from app.schemas.task_spec import SweTaskSpec

_NEW_TEST_PATCH = """diff --git a/test_marker.py b/test_marker.py
new file mode 100644
--- /dev/null
+++ b/test_marker.py
@@ -0,0 +1,2 @@
+def test_marker():
+    assert True
"""


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "widget.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    return repo


class TestSchema:
    def test_test_patch_defaults_empty(self) -> None:
        spec = SweTaskSpec(
            repo="owner/name",
            base_commit="c" * 40,
            problem_statement="p",
            fail_to_pass=["t.py::t"],
        )
        assert spec.test_patch == ""
        assert spec.environment.setup_commands == []

    def test_from_swebench_parses_test_patch_and_setup_commands(self) -> None:
        raw = {
            "repo": "owner/name",
            "base_commit": "c" * 40,
            "problem_statement": "p",
            "FAIL_TO_PASS": json.dumps(["t.py::t"]),
            "PASS_TO_PASS": json.dumps([]),
            "test_patch": _NEW_TEST_PATCH,
            "environment": {"setup_commands": ["uv sync"]},
        }
        spec = SweTaskSpec.from_swebench_instance(raw)
        assert spec.test_patch == _NEW_TEST_PATCH
        assert spec.environment.setup_commands == ["uv sync"]


class TestApplyTestPatch:
    def test_empty_patch_is_noop(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        apply_test_patch(repo, "")
        assert not (repo / "test_marker.py").exists()

    def test_applies_unified_diff(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        apply_test_patch(repo, _NEW_TEST_PATCH)
        assert (repo / "test_marker.py").exists()
        assert "test_marker" in (repo / "test_marker.py").read_text()

    def test_bad_patch_raises(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        try:
            apply_test_patch(repo, "this is not a patch")
        except TestPatchError as exc:
            assert str(exc)
        else:
            raise AssertionError("TestPatchError not raised for garbage patch")


class TestEnvironmentSetup:
    def test_no_commands_is_noop(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        assert run_environment_setup(repo, []) == []

    def test_runs_commands_in_the_repo(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        results = run_environment_setup(
            repo, ["python -c \"open('setup.marker', 'w').write('ok')\""]
        )
        assert len(results) == 1
        assert results[0].exit_code == 0
        assert (repo / "setup.marker").read_text() == "ok"

    def test_failure_raises_with_command(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        try:
            run_environment_setup(repo, ["python -c \"raise SystemExit(3)\""])
        except EnvironmentSetupError as exc:
            assert "raise SystemExit" in str(exc)
        else:
            raise AssertionError("EnvironmentSetupError not raised")


class TestProbeIsolation:
    def test_probe_uses_harness_python_without_repo_venv(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        command = _pytest_command_for("tests/test_x.py::test_y", repo)
        assert command.startswith("python -m pytest")
        assert "-o addopts=" in command

    def test_probe_prefers_repo_local_venv(self, tmp_path: Path) -> None:
        repo = _git_repo(tmp_path)
        venv_bin = repo / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        command = _pytest_command_for("tests/test_x.py::test_y", repo)
        assert command.startswith(f"{python} -m pytest")

    def test_probe_venv_path_is_absolute_for_relative_repo(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Regression: probes run with cwd=repo_path, so a RELATIVE repo path
        would make a relative venv reference resolve inside the repo and
        crash the gate with FileNotFoundError. The venv path must be
        absolute no matter how repo_path arrives."""
        repo = _git_repo(tmp_path)
        venv_bin = repo / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        monkeypatch.chdir(tmp_path)
        command = _pytest_command_for("tests/test_x.py::test_y", Path("repo"))
        assert command.startswith(f"{python.resolve()} -m pytest")


class TestGateInfraFailureIsInconclusive:
    def test_probe_spawn_failure_is_inconclusive_not_crash(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Regression: if the probe interpreter cannot even spawn (missing
        binary, permission), the gate must record inconclusive and block —
        never crash with a traceback (which is neither evidence nor a
        verdict)."""
        import app.core.task_spec_gate as gate_module

        repo = _git_repo(tmp_path)

        def boom(*args, **kwargs):
            raise FileNotFoundError(".venv/bin/python does not exist")

        monkeypatch.setattr(gate_module.TestRunner, "run", boom)
        spec = SweTaskSpec(
            repo="owner/name",
            base_commit="c" * 40,
            problem_statement="p",
            fail_to_pass=["t.py::t"],
        )
        result = gate_module.evaluate_negative_contract(spec, repo)
        assert result.passed is False
        assert result.reasons
        assert "could not run" in result.reasons[0].lower()
