"""The differential migration oracle — deterministic proof that NEW behaves like OLD.

Two phases:
  1. ``capture_golden(old_spec, cases)``  — run the OLD system on every case, record its
     outputs. This is the source of truth, captured ONCE and then sealed.
  2. ``verify(new_spec, cases, golden)``  — run the NEW system on the same cases and
     compare against the sealed golden set, emitting a per-case verdict with diffs.

No LLM. No worker. The worker that performs the migration edits the new system; it never
touches the golden set or this comparison. The outer layer owns both — that is the seal.
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path

from app.schemas.oracle import (
    CaseResult,
    GoldenCase,
    GoldenSet,
    Normalization,
    OracleCase,
    OracleReport,
    RunnerSpec,
)


class OracleError(Exception):
    """A case could not be executed (bad command, timeout, missing output file)."""


class DifferentialOracle:
    def __init__(self, normalization: Normalization | None = None) -> None:
        self.normalization = normalization or Normalization()

    # -- public API ----------------------------------------------------------------------

    def capture_golden(
        self, source_spec: RunnerSpec, cases: list[OracleCase], *, label: str = ""
    ) -> GoldenSet:
        """Run the OLD system on every case and freeze its outputs as the golden set."""
        golden_cases: list[GoldenCase] = []
        for case in cases:
            output, exit_code = self._run(source_spec, case)
            golden_cases.append(
                GoldenCase(name=case.name, output=output, exit_code=exit_code)
            )
        return GoldenSet(
            captured_from=label or " ".join(source_spec.command),
            normalization=self.normalization,
            cases=golden_cases,
        )

    def verify(
        self, candidate_spec: RunnerSpec, cases: list[OracleCase], golden: GoldenSet
    ) -> OracleReport:
        """Run the NEW system on every case and compare to the sealed golden set."""
        results: list[CaseResult] = []
        for case in cases:
            golden_case = golden.case(case.name)
            if golden_case is None:
                results.append(
                    CaseResult(
                        name=case.name,
                        equivalent=False,
                        expected="",
                        actual="",
                        note="no golden output captured for this case",
                    )
                )
                continue
            actual, exit_code = self._run(candidate_spec, case)
            expected_norm = self._canonical(golden_case.output)
            actual_norm = self._canonical(actual)
            equivalent = expected_norm == actual_norm
            diff = "" if equivalent else self._diff(expected_norm, actual_norm, case.name)
            note = (
                ""
                if equivalent
                else f"exit_code old={golden_case.exit_code} new={exit_code}"
            )
            results.append(
                CaseResult(
                    name=case.name,
                    equivalent=equivalent,
                    expected=golden_case.output,
                    actual=actual,
                    diff=diff,
                    note=note,
                )
            )
        passed = sum(1 for r in results if r.equivalent)
        return OracleReport(
            equivalent=all(r.equivalent for r in results) and len(results) == len(cases),
            total=len(cases),
            passed=passed,
            failed=len(cases) - passed,
            cases=results,
        )

    # -- execution -----------------------------------------------------------------------

    def _run(self, spec: RunnerSpec, case: OracleCase) -> tuple[str, int]:
        cwd = Path(spec.cwd) if spec.cwd else Path.cwd()
        for rel, content in case.input_files.items():
            target = cwd / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        argv = [*spec.command, *case.args]
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                input=case.stdin,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                check=False,
                env={**_inherit_env(), **spec.env} if spec.env else None,
            )
        except FileNotFoundError as exc:
            raise OracleError(f"case {case.name!r}: command not found: {argv[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise OracleError(
                f"case {case.name!r}: timed out after {spec.timeout_seconds}s"
            ) from exc
        if case.output_file is not None:
            output_path = cwd / case.output_file
            if not output_path.exists():
                raise OracleError(
                    f"case {case.name!r}: expected output file {case.output_file!r} was not written"
                )
            return output_path.read_text(encoding="utf-8"), completed.returncode
        return completed.stdout, completed.returncode

    # -- comparison ----------------------------------------------------------------------

    def _canonical(self, text: str) -> str:
        norm = self.normalization
        if norm.normalize_line_endings:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        if norm.strip_trailing_whitespace:
            lines = [line.rstrip() for line in lines]
        if norm.ignore_blank_lines:
            lines = [line for line in lines if line.strip()]
        text = "\n".join(lines)
        if norm.rstrip_final_newline:
            text = text.rstrip("\n")
        return text

    def _diff(self, expected: str, actual: str, name: str) -> str:
        return "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"old::{name}",
                tofile=f"new::{name}",
                lineterm="",
            )
        )


def _inherit_env() -> dict[str, str]:
    import os

    return dict(os.environ)
