"""Negative-contract gate for task specs (§3.4.2 planning-as-contract).

Before any worker is dispatched, the harness must prove the task's bug
actually exists at ``base_commit``: every ``fail_to_pass`` test is run and
must FAIL. This is the deterministic sensor that stops an agent from
"solving" a non-reproducible problem (or a problem that was never there)
and burning the run budget on it.

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
