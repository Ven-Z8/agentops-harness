"""Task-spec contract gates (§3.4.2 planning-as-contract).

Two deterministic sensors bracket a governed run:

NEGATIVE gate (pre-dispatch): the harness must prove the task's bug
actually exists at ``base_commit``: every ``fail_to_pass`` test is run and
must FAIL. This stops an agent from "solving" a non-reproducible problem
(or a problem that was never there) and burning the run budget on it.

POSITIVE gate (post-run, AO-D03-01): on the patched tree every
``fail_to_pass`` test must now PASS and every ``pass_to_pass`` test must
STILL pass — a fix that regresses existing behavior violates the contract
and fails the run (execution success ≠ evaluation success).

Fail-closed semantics:

- a fail_to_pass test that PASSES at base ⇒ the bug is NOT reproducible
  ⇒ gate blocks (the spec's premise is wrong, fix the spec);
- a test that cannot run (collection error, missing file, timeout) ⇒
  INCONCLUSIVE, never an inferred pass ⇒ gate blocks with the reason;
- a test that fails ⇒ the negative contract holds for that test.

The gate's evidence (commands + exit codes + output tails) is returned in
the result so it lands in the run's execution logs and evidence bundle —
replayability is the point (§5.2.1).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.test_runner import TestRunner
from app.schemas.task_spec import SweTaskSpec


class TestPatchError(RuntimeError):
    """The spec's test patch could not be applied to the base tree.

    Fail-closed: a patch that does not apply means the spec is invalid for
    this base_commit — the contract tests cannot even exist, so no gate can
    run and no worker may dispatch.
    """


class EnvironmentSetupError(RuntimeError):
    """A declared environment setup command failed.

    Fail-closed: an environment that cannot be prepared is an unverified
    environment (AO-D03-02 class) — probes in it would prove nothing.
    """


@dataclass(frozen=True)
class EnvironmentSetupResult:
    command: str
    exit_code: int
    output_tail: str = ""


def apply_test_patch(repo_path: Path, test_patch: str) -> None:
    """Apply the spec's unified diff to the cloned base tree (before gating).

    SWE-bench-shaped instances carry their failing tests as a patch; the
    tests often do not exist at base_commit. Empty patch = no-op. Failure
    raises TestPatchError with git's stderr so the reason lands in evidence.
    """
    if not test_patch.strip():
        return
    completed = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=test_patch,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise TestPatchError(
            f"test_patch does not apply to the base tree (git apply exit "
            f"{completed.returncode}): {(completed.stderr or '').strip()[:500]}"
        )


def run_environment_setup(
    repo_path: Path,
    setup_commands: list[str],
    timeout_seconds: int = 900,
) -> list[EnvironmentSetupResult]:
    """Run the spec's declared environment-prep commands inside the clone.

    Commands run sequentially, cwd=repo, no shell (shlex-split) — they are
    operator-authored environment identity, e.g. 'uv sync --extra allauth'.
    Any non-zero exit raises EnvironmentSetupError (fail-closed).
    """
    results: list[EnvironmentSetupResult] = []
    for command in setup_commands:
        argv = shlex.split(command)
        completed = subprocess.run(
            argv,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output_tail = ((completed.stdout or "") + "\n" + (completed.stderr or ""))[-2000:]
        results.append(
            EnvironmentSetupResult(
                command=command, exit_code=completed.returncode, output_tail=output_tail
            )
        )
        if completed.returncode != 0:
            raise EnvironmentSetupError(
                f"Environment setup failed: {command!r} exited "
                f"{completed.returncode}. Tail: {output_tail[-400:]}"
            )
    return results


@dataclass(frozen=True)
class NegativeContractCommandResult:
    """One fail_to_pass probe: command, exit code, and an output tail."""

    command: str
    exit_code: int
    output_tail: str = ""


@dataclass(frozen=True)
class NegativeContractGateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    command_results: list[NegativeContractCommandResult] = field(default_factory=list)


def _pytest_command_for(test_id: str, repo_path: Path) -> str:
    # test ids are pytest node ids (file::test); shell-quote the id so
    # ids containing '[]' or '::' survive the command line intact.
    #
    # Probe isolation: `-o addopts=` clears the repo's global pytest add-ons
    # (coverage floors and the like) so they cannot turn a passing test into
    # a failing command — dmr's own test-command uses the same trick. When
    # the clone carries a repo-local .venv, probes use it: the target's
    # dependencies are the target's business, not the harness's.
    python = "python"
    venv_python = Path(repo_path) / ".venv" / "bin" / "python"
    if venv_python.exists():
        # Absolute, but WITHOUT resolving symlinks: .venv/bin/python is a
        # symlink and the venv only activates when invoked through it —
        # resolve() would follow it to the bare base interpreter, which has
        # none of the target's packages (and then 'No module named pytest'
        # masquerades as test failures on both gates).
        python = os.path.abspath(venv_python)
    return f"{python} -m pytest {shlex.quote(test_id)} -q -o addopts="


def evaluate_negative_contract(
    spec: SweTaskSpec,
    repo_path: Path,
    timeout_seconds: int = 300,
) -> NegativeContractGateResult:
    """Run every fail_to_pass test at base_commit; the gate passes only when
    ALL of them fail (proving the bug is reproducible)."""

    runner = TestRunner()
    reasons: list[str] = []
    results: list[NegativeContractCommandResult] = []

    for test_id in spec.fail_to_pass:
        command = _pytest_command_for(test_id, repo_path)
        try:
            summary = runner.run(
                Path(repo_path), commands=[command], timeout_seconds=timeout_seconds
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # The probe could not even run (missing interpreter, spawn
            # failure). That is evidence of nothing — inconclusive, never a
            # crash and never an inferred pass.
            results.append(
                NegativeContractCommandResult(
                    command=command, exit_code=-1, output_tail=str(exc)
                )
            )
            reasons.append(
                f"Inconclusive: {test_id} could not run ({exc}); a test that "
                f"cannot execute cannot prove the bug exists."
            )
            continue
        # TestRunner runs exactly the one command we passed.
        result = summary.commands[0]
        output_tail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-2000:]
        results.append(
            NegativeContractCommandResult(
                command=command,
                exit_code=result.exit_code,
                output_tail=output_tail,
            )
        )
        if result.exit_code == 0:
            reasons.append(
                f"Negative contract violated: {test_id} PASSES at base_commit "
                f"({spec.base_commit[:12]}) — the bug it names is not "
                f"reproducible; fix the spec before running a worker."
            )
        elif result.exit_code != 0 and "No module named pytest" in output_tail:
            # A probe that cannot even import pytest proves nothing — its
            # exit 1 is 'python: No module named pytest', not a test failure.
            # (Seen live: invoking a venv's resolved base interpreter instead
            # of the venv itself.) Inconclusive, never a proven bug.
            reasons.append(
                f"Inconclusive: {test_id} could not run — pytest is missing from "
                f"the probe environment (exit {result.exit_code}); fix the spec's "
                f"environment setup before running a worker."
            )
        elif result.exit_code in (2, 4, 5) or "ERROR" in (result.stderr or "")[:2000]:
            # pytest exit 2 = interrupted/collection error, 4 = usage error,
            # 5 = no tests collected. A test that cannot run proves nothing —
            # inconclusive blocks, never an inferred pass.
            reasons.append(
                f"Inconclusive: {test_id} could not run (exit {result.exit_code}); "
                f"a test that cannot execute cannot prove the bug exists."
            )

    # PASSED only when every fail_to_pass test genuinely failed (exit != 0
    # and not an error-state exit). exit codes 1 and 3 are honest failures;
    # anything else is inconclusive (already recorded above).
    error_exits = {2, 4, 5}
    passed = all(
        r.exit_code != 0 and r.exit_code not in error_exits for r in results
    ) and not reasons

    return NegativeContractGateResult(
        passed=passed,
        reasons=reasons,
        command_results=results,
    )


# ---------------------------------------------------------------------------
# Positive-contract gate — AO-D03-01
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositiveContractCommandResult:
    """One contract probe on the patched tree: command, exit code, output tail."""

    command: str
    exit_code: int
    output_tail: str = ""


@dataclass(frozen=True)
class PositiveContractGateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    command_results: list[PositiveContractCommandResult] = field(default_factory=list)


def evaluate_positive_contract(
    spec: SweTaskSpec,
    repo_path: Path,
    timeout_seconds: int = 300,
) -> PositiveContractGateResult:
    """Run the contract on the PATCHED tree after the run.

    The positive contract holds only when BOTH halves pass:

    - every ``fail_to_pass`` test now PASSES (the fix resolved the bug); and
    - every ``pass_to_pass`` test STILL passes (the fix regressed nothing).

    This is the deterministic sensor behind "execution success ≠ evaluation
    success" (AO-D01-02): a worker that exits 0 is not the same as a tree that
    satisfies the contract. Fail-closed, mirroring the negative gate — a test
    that cannot run is inconclusive, never an inferred pass.
    """

    runner = TestRunner()
    reasons: list[str] = []
    results: list[PositiveContractCommandResult] = []
    error_exits = {2, 4, 5}

    def _probe(test_id: str, *, kind: str) -> None:
        command = _pytest_command_for(test_id, repo_path)
        try:
            summary = runner.run(
                Path(repo_path), commands=[command], timeout_seconds=timeout_seconds
            )
        except (OSError, subprocess.SubprocessError) as exc:
            results.append(
                PositiveContractCommandResult(
                    command=command, exit_code=-1, output_tail=str(exc)
                )
            )
            reasons.append(
                f"Inconclusive: {kind} {test_id} could not run on the patched "
                f"tree ({exc}); a test that cannot execute proves nothing — "
                f"never an inferred pass."
            )
            return
        result = summary.commands[0]
        output_tail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-2000:]
        results.append(
            PositiveContractCommandResult(
                command=command,
                exit_code=result.exit_code,
                output_tail=output_tail,
            )
        )
        if result.exit_code == 0:
            return
        if result.exit_code in error_exits or "ERROR" in (result.stderr or "")[:2000]:
            reasons.append(
                f"Inconclusive: {kind} {test_id} could not run on the patched tree "
                f"(exit {result.exit_code}); a test that cannot execute proves "
                f"nothing — never an inferred pass."
            )
        elif kind == "FAIL_TO_PASS":
            reasons.append(
                f"Positive contract violated: FAIL_TO_PASS {test_id} still fails on "
                f"the patched tree (exit {result.exit_code}) — the bug is not fixed."
            )
        else:
            reasons.append(
                f"Positive contract violated: PASS_TO_PASS {test_id} regressed on the "
                f"patched tree (exit {result.exit_code}) — the fix broke behavior "
                f"that previously passed."
            )

    for test_id in spec.fail_to_pass:
        _probe(test_id, kind="FAIL_TO_PASS")
    for test_id in spec.pass_to_pass:
        _probe(test_id, kind="PASS_TO_PASS")

    return PositiveContractGateResult(
        passed=not reasons and all(r.exit_code == 0 for r in results),
        reasons=reasons,
        command_results=results,
    )
