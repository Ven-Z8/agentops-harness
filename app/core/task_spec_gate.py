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

from dataclasses import dataclass, field
from pathlib import Path

from app.core.test_runner import TestRunner
from app.schemas.task_spec import SweTaskSpec


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


def _pytest_command_for(test_id: str) -> str:
    # test ids are pytest node ids (file::test); shell-quote the id so
    # ids containing '[]' or '::' survive the command line intact.
    import shlex

    return f"python -m pytest {shlex.quote(test_id)} -q"


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
        command = _pytest_command_for(test_id)
        summary = runner.run(Path(repo_path), commands=[command], timeout_seconds=timeout_seconds)
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
        command = _pytest_command_for(test_id)
        summary = runner.run(
            Path(repo_path), commands=[command], timeout_seconds=timeout_seconds
        )
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
