"""Task-spec contract tests (Phase 2 kernel entry, AO-D03 class).

The SWE-bench-style task tuple: repo, base_commit, problem_statement,
FAIL_TO_PASS, PASS_TO_PASS, and environment identity. The spec is the
deterministic contract that makes an issue run reproducible rather than
repeatable — the negative-contract gate proves the bug exists at
base_commit BEFORE the worker starts, and the positive contract proves
the fix after. Test-first: these tests are red until the schema + gate
exist (see ROADMAP.md "What remains", item 3 — ExperimentSpec /
ExecutionProvider / EvaluationProvider contracts; the issue path is the
coding-agent benchmark's execution provider).
"""

from __future__ import annotations

import subprocess as sp
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.task_spec import SweTaskSpec


@dataclass(frozen=True)
class FixtureRepo:
    """A hermetic git repo plus the pinned hash of its single commit."""

    path: Path
    commit_hash: str


class TestSweTaskSpecSchema:
    def test_spec_requires_core_fields(self) -> None:
        with pytest.raises(ValidationError):
            SweTaskSpec()  # no fields -> must not validate

    def test_spec_roundtrip_and_identity(self) -> None:
        spec = SweTaskSpec(
            repo="piskoviste/pisek",
            base_commit="b86d1d7",
            problem_statement="Judge feedback lacks the log path.",
            fail_to_pass=["tests/test_kasiopea.py::TestBadJudgeFeedbackMessage"],
            pass_to_pass=["tests/test_kasiopea.py::TestSumKasiopea"],
        )
        dumped = spec.model_dump()
        assert dumped["repo"] == "piskoviste/pisek"
        assert dumped["fail_to_pass"] == [
            "tests/test_kasiopea.py::TestBadJudgeFeedbackMessage"
        ]
        # identity: a spec is reproducible by its pinned inputs
        assert SweTaskSpec(**dumped) == spec

    def test_spec_requires_at_least_one_fail_to_pass(self) -> None:
        with pytest.raises(ValidationError):
            SweTaskSpec(
                repo="a/b",
                base_commit="c0ffee",
                problem_statement="p",
                fail_to_pass=[],  # negative contract needs a failing test to prove
                pass_to_pass=["tests/x.py::test_ok"],
            )

    def test_spec_from_swebench_json_tuple(self) -> None:
        raw = {
            "repo": "psf/requests",
            "base_commit": "abc123",
            "problem_statement": "Session fails on redirect",
            "FAIL_TO_PASS": "[\"tests/test_requests.py::TestRedirects::test_pass\"]",
            "PASS_TO_PASS": "[\"tests/test_requests.py::test_basics\"]",
        }
        spec = SweTaskSpec.from_swebench_instance(raw)
        assert spec.fail_to_pass == ["tests/test_requests.py::TestRedirects::test_pass"]
        assert spec.pass_to_pass == ["tests/test_requests.py::test_basics"]
        assert spec.repo == "psf/requests"
        assert spec.base_commit == "abc123"

    def test_spec_from_swebench_parses_environment_identity(self) -> None:
        """AO-D03-02: a spec may pin its execution environment. The parser must
        carry the identity through so enforcement can act on it."""
        digest = "sha256:" + "ab" * 32
        raw = {
            "repo": "psf/requests",
            "base_commit": "abc123",
            "problem_statement": "Session fails on redirect",
            "FAIL_TO_PASS": "[\"tests/test_requests.py::test_pass\"]",
            "environment": {
                "image_digest": digest,
                "python_version": "3.12",
                "lockfile_digest": "sha256:" + "cd" * 32,
            },
        }
        spec = SweTaskSpec.from_swebench_instance(raw)
        assert spec.environment.image_digest == digest
        assert spec.environment.python_version == "3.12"
        assert spec.environment.lockfile_digest == "sha256:" + "cd" * 32

    def test_spec_from_swebench_without_environment_defaults_empty(self) -> None:
        raw = {
            "repo": "psf/requests",
            "base_commit": "abc123",
            "problem_statement": "x",
            "FAIL_TO_PASS": "[\"tests/test_a.py::test_b\"]",
        }
        spec = SweTaskSpec.from_swebench_instance(raw)
        assert spec.environment.image_digest is None
        assert spec.environment.lockfile_digest is None
        assert spec.environment.python_version is None


class TestNegativeContractGate:
    def test_gate_blocks_when_fail_to_pass_passes_at_base(self, tmp_path: Path) -> None:
        """If FAIL_TO_PASS passes at base_commit, the bug is not reproducible —
        the run must not start (fail closed, AO-D01-04 class)."""
        from app.core.task_spec_gate import evaluate_negative_contract

        repo = _fixture_repo(tmp_path, bug_present=False)
        spec = _spec_for(repo, fail_to_pass=["tests/test_widget.py::test_keep_name"])

        gate = evaluate_negative_contract(spec, repo.path)
        assert gate.passed is False
        assert any(
            "not reproducible" in r or "PASSES at base_commit" in r for r in gate.reasons
        ), gate.reasons

    def test_gate_passes_when_bug_reproduces(self, tmp_path: Path) -> None:
        from app.core.task_spec_gate import evaluate_negative_contract

        repo = _fixture_repo(tmp_path, bug_present=True)
        spec = _fixture_spec(repo)

        gate = evaluate_negative_contract(spec, repo.path)
        assert gate.passed is True
        assert gate.reasons == [] or all("reproduc" not in r.lower() for r in gate.reasons)

    def test_gate_blocks_when_test_runner_errors(self, tmp_path: Path) -> None:
        """A test command that errors (cannot run) is NOT a pass — it is
        inconclusive, and inconclusive never becomes an inferred pass."""
        from app.core.task_spec_gate import evaluate_negative_contract

        repo = _fixture_repo(tmp_path, bug_present=True)
        spec = _spec_for(repo, fail_to_pass=["tests/test_widget.py::test_missing_file"])

        gate = evaluate_negative_contract(spec, repo.path)
        assert gate.passed is False
        assert gate.reasons, "inconclusive must be recorded with a reason"

    def test_gate_records_commands_and_exit_codes(self, tmp_path: Path) -> None:
        """The gate's evidence must be inspectable: which commands ran, what
        exited non-zero (negative contract) — replayability (§5.2.1)."""
        from app.core.task_spec_gate import evaluate_negative_contract

        repo = _fixture_repo(tmp_path, bug_present=True)
        spec = _fixture_spec(repo)

        gate = evaluate_negative_contract(spec, repo.path)
        assert gate.command_results, "evidence must contain command results"
        for result in gate.command_results:
            assert result.command  # every result names its command
            assert result.exit_code != 0  # negative contract: all FAIL_TO_PASS must fail


class TestPositiveContractGate:
    """AO-D03-01: after the run, on the PATCHED tree, every FAIL_TO_PASS test
    must pass and every PASS_TO_PASS test must STILL pass. A fix that does not
    resolve the bug — or that regresses existing behavior — violates the
    contract and must fail the run (honesty: execution success ≠ evaluation
    success, AO-D01-02)."""

    def test_gate_passes_when_fix_holds_and_no_regression(self, tmp_path: Path) -> None:
        from app.core.task_spec_gate import evaluate_positive_contract

        repo = _two_test_repo(tmp_path, source=_FIXED_SOURCE)
        spec = _two_test_spec(repo)

        gate = evaluate_positive_contract(spec, repo.path)
        assert gate.passed is True
        assert gate.reasons == []
        assert len(gate.command_results) == 2  # one FAIL_TO_PASS + one PASS_TO_PASS
        assert all(r.exit_code == 0 for r in gate.command_results)

    def test_gate_fails_when_fail_to_pass_still_fails(self, tmp_path: Path) -> None:
        """The worker 'finished' but the bug is still there — the contract
        must fail the run, never accept an unfixed tree."""
        from app.core.task_spec_gate import evaluate_positive_contract

        repo = _two_test_repo(tmp_path, source=_BUGGY_SOURCE)
        spec = _two_test_spec(repo)

        gate = evaluate_positive_contract(spec, repo.path)
        assert gate.passed is False
        assert any(
            "FAIL_TO_PASS" in r and "still fails" in r.lower() for r in gate.reasons
        ), gate.reasons

    def test_gate_fails_when_pass_to_pass_regresses(self, tmp_path: Path) -> None:
        """A fix that breaks behavior that must keep working is a regression —
        it violates the positive contract even though FAIL_TO_PASS passes."""
        from app.core.task_spec_gate import evaluate_positive_contract

        repo = _two_test_repo(tmp_path, source=_REGRESSED_SOURCE)
        spec = _two_test_spec(repo)

        gate = evaluate_positive_contract(spec, repo.path)
        assert gate.passed is False
        assert any("regress" in r.lower() for r in gate.reasons), gate.reasons

    def test_gate_blocks_inconclusive_tests(self, tmp_path: Path) -> None:
        """A named test that cannot run (missing node) proves nothing —
        inconclusive, never an inferred pass."""
        from app.core.task_spec_gate import evaluate_positive_contract

        repo = _two_test_repo(tmp_path, source=_FIXED_SOURCE)
        spec = SweTaskSpec(
            repo="example/widgetlib",
            base_commit=repo.commit_hash,
            problem_statement="reset(keep_name=True) drops the name",
            fail_to_pass=["tests/test_widget.py::test_missing_node"],
            pass_to_pass=["tests/test_widget.py::test_default_clears"],
        )

        gate = evaluate_positive_contract(spec, repo.path)
        assert gate.passed is False
        assert any("Inconclusive" in r for r in gate.reasons), gate.reasons


# ---------------------------------------------------------------------------
# helpers — tiny hermetic fixture repo with a real bug at a real commit
# ---------------------------------------------------------------------------


def _fixture_repo(tmp_path: Path, bug_present: bool) -> FixtureRepo:
    """A real git repo with a real failing test (or not) at its single commit."""

    repo = tmp_path / ("widgetlib-bug" if bug_present else "widgetlib-clean")
    repo.mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_widget.py").write_text(
        "from widgetlib import Widget\n\n"
        "def test_keep_name():\n"
        "    w = Widget(name='kettle')\n"
        "    w.reset(keep_name=True)\n"
        "    assert w.name == 'kettle'\n"
    )
    clean_source = (
        "class Widget:\n"
        "    def __init__(self, name=None):\n"
        "        self.name = name\n"
        "    def reset(self, keep_name=False):\n"
        "        self.name = self.name if keep_name else None\n"
    )
    buggy_source = (
        "class Widget:\n"
        "    def __init__(self, name=None):\n"
        "        self.name = name\n"
        "    def reset(self, keep_name=False):\n"
        "        self.name = None  # BUG: drops the name even when keep_name=True\n"
    )
    (repo / "widgetlib.py").write_text(buggy_source if bug_present else clean_source)
    for cmd in (
        ["git", "init", "--quiet"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "init"],
    ):
        sp.run(cmd, cwd=repo, capture_output=True, check=True)
    # Pin the real commit hash so specs use a fixed ref, never a movable
    # one (the schema rejects HEAD on purpose).
    head = sp.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    )
    return FixtureRepo(path=repo, commit_hash=head.stdout.strip())


def _spec_for(repo: FixtureRepo, fail_to_pass: list[str]) -> SweTaskSpec:
    return SweTaskSpec(
        repo="example/widgetlib",
        base_commit=repo.commit_hash,
        problem_statement="reset(keep_name=True) drops the name",
        fail_to_pass=fail_to_pass,
        pass_to_pass=[],
    )


def _fixture_spec(repo: FixtureRepo) -> SweTaskSpec:
    return _spec_for(repo, fail_to_pass=["tests/test_widget.py::test_keep_name"])


# ---------------------------------------------------------------------------
# helpers — positive-contract fixture: FAIL_TO_PASS + PASS_TO_PASS in one repo
# ---------------------------------------------------------------------------

_BUGGY_SOURCE = (
    "class Widget:\n"
    "    def __init__(self, name=None):\n"
    "        self.name = name\n"
    "    def reset(self, keep_name=False):\n"
    "        self.name = None  # BUG: drops the name even when keep_name=True\n"
)
_FIXED_SOURCE = (
    "class Widget:\n"
    "    def __init__(self, name=None):\n"
    "        self.name = name\n"
    "    def reset(self, keep_name=False):\n"
    "        self.name = self.name if keep_name else None\n"
)
# F2P passes but PASS_TO_PASS regresses: reset now keeps the name ALWAYS,
# so the default-clears behavior is broken by the "fix".
_REGRESSED_SOURCE = (
    "class Widget:\n"
    "    def __init__(self, name=None):\n"
    "        self.name = name\n"
    "    def reset(self, keep_name=False):\n"
    "        pass  # 'fix' keeps the name unconditionally — regresses the default\n"
)

_TWO_TESTS = (
    "from widgetlib import Widget\n\n"
    "def test_keep_name():\n"
    "    w = Widget(name='kettle')\n"
    "    w.reset(keep_name=True)\n"
    "    assert w.name == 'kettle'\n\n"
    "def test_default_clears():\n"
    "    w = Widget(name='kettle')\n"
    "    w.reset()\n"
    "    assert w.name is None\n"
)


def _two_test_repo(tmp_path: Path, source: str) -> FixtureRepo:
    """Real git repo with one FAIL_TO_PASS test (test_keep_name) and one
    PASS_TO_PASS test (test_default_clears); `source` controls which state
    the tree is in (buggy / fixed / regressed)."""
    repo = tmp_path / "widgetlib-two-tests"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_widget.py").write_text(_TWO_TESTS)
    (repo / "widgetlib.py").write_text(source)
    for cmd in (
        ["git", "init", "--quiet"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "init"],
    ):
        sp.run(cmd, cwd=repo, capture_output=True, check=True)
    head = sp.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    )
    return FixtureRepo(path=repo, commit_hash=head.stdout.strip())


def _two_test_spec(repo: FixtureRepo) -> SweTaskSpec:
    return SweTaskSpec(
        repo="example/widgetlib",
        base_commit=repo.commit_hash,
        problem_statement="reset(keep_name=True) drops the name",
        fail_to_pass=["tests/test_widget.py::test_keep_name"],
        pass_to_pass=["tests/test_widget.py::test_default_clears"],
    )
