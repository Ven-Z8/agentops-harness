"""Unit tests for the differential migration oracle.

Deterministic and dependency-free: the "old" and "new" systems are tiny Python scripts
written into tmp_path. This proves the oracle's contract — capture golden from OLD,
verify NEW against it, detect drift, surface a diff — without needing COBOL, a compiler,
or an API key. The language-agnostic design is the point: the same oracle that passes
here will judge a GnuCOBOL binary against a Python port unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.core.oracle import DifferentialOracle, OracleError
from app.schemas.oracle import OracleCase, RunnerSpec

# An "old" system: reads two ints on stdin, prints their sum in a fixed format.
_OLD = """\
import sys
a, b = (int(x) for x in sys.stdin.read().split())
print(f"sum={a + b}")
"""

# A faithful migration — different code, identical behavior.
_NEW_FAITHFUL = """\
import sys
nums = [int(x) for x in sys.stdin.read().split()]
print("sum=%d" % sum(nums))
"""

# A buggy migration — off-by-one drift the oracle must catch.
_NEW_DRIFT = """\
import sys
a, b = (int(x) for x in sys.stdin.read().split())
print(f"sum={a + b + 1}")
"""

_CASES = [
    OracleCase(name="small", stdin="2 3"),
    OracleCase(name="zero", stdin="0 0"),
    OracleCase(name="large", stdin="1000 2000"),
]


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_faithful_migration_is_equivalent(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.py", _OLD)
    new = _write(tmp_path / "new.py", _NEW_FAITHFUL)
    oracle = DifferentialOracle()

    golden = oracle.capture_golden(
        RunnerSpec(command=[sys.executable, str(old)]), _CASES, label="old.py"
    )
    assert len(golden.cases) == 3
    assert golden.case("small").output.strip() == "sum=5"

    report = oracle.verify(RunnerSpec(command=[sys.executable, str(new)]), _CASES, golden)
    assert report.equivalent
    assert report.passed == 3
    assert report.failed == 0
    assert "EQUIVALENT" in report.summary()


def test_drift_is_detected_with_a_diff(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.py", _OLD)
    new = _write(tmp_path / "new.py", _NEW_DRIFT)
    oracle = DifferentialOracle()

    golden = oracle.capture_golden(RunnerSpec(command=[sys.executable, str(old)]), _CASES)
    report = oracle.verify(RunnerSpec(command=[sys.executable, str(new)]), _CASES, golden)

    assert not report.equivalent
    assert report.failed == 3
    assert "DRIFT DETECTED" in report.summary()
    drift = next(c for c in report.cases if c.name == "small")
    assert drift.expected.strip() == "sum=5"
    assert drift.actual.strip() == "sum=6"
    assert "sum=5" in drift.diff and "sum=6" in drift.diff  # unified diff shows both sides


def test_golden_is_sealed_new_cannot_change_expected(tmp_path: Path) -> None:
    """The verdict comes from the captured golden, not from re-running OLD.

    Even if the old source is later mutated to agree with a buggy new system, a golden
    captured BEFORE the mutation still judges against the original behavior. This is the
    seal: the worker editing the repo cannot retroactively move the goalposts.
    """
    old = _write(tmp_path / "old.py", _OLD)
    oracle = DifferentialOracle()
    golden = oracle.capture_golden(RunnerSpec(command=[sys.executable, str(old)]), _CASES)

    # Worker tampers with BOTH the new system and the old source to make them agree.
    new = _write(tmp_path / "new.py", _NEW_DRIFT)
    _write(old, _NEW_DRIFT)  # old.py now also produces sum+1

    report = oracle.verify(RunnerSpec(command=[sys.executable, str(new)]), _CASES, golden)
    assert not report.equivalent  # sealed golden still encodes the original sum=5 behavior


def test_normalization_absorbs_trailing_whitespace(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.py", 'print("report  ")')  # trailing spaces
    new = _write(tmp_path / "new.py", 'print("report")')  # none
    oracle = DifferentialOracle()
    cases = [OracleCase(name="only")]
    golden = oracle.capture_golden(RunnerSpec(command=[sys.executable, str(old)]), cases)
    report = oracle.verify(RunnerSpec(command=[sys.executable, str(new)]), cases, golden)
    assert report.equivalent  # cosmetic trailing whitespace is not behavioral drift


def test_output_file_capture(tmp_path: Path) -> None:
    """Batch-style: the program writes a report FILE; the oracle captures that, not stdout."""
    prog = _write(
        tmp_path / "batch.py",
        'open("out.txt", "w").write("TOTAL: 42\\n")',
    )
    oracle = DifferentialOracle()
    cases = [OracleCase(name="batch", output_file="out.txt")]
    spec = RunnerSpec(command=[sys.executable, str(prog)], cwd=str(tmp_path))
    golden = oracle.capture_golden(spec, cases)
    assert golden.case("batch").output.strip() == "TOTAL: 42"
    report = oracle.verify(spec, cases, golden)
    assert report.equivalent


def test_missing_command_raises_oracle_error(tmp_path: Path) -> None:
    oracle = DifferentialOracle()
    cases = [OracleCase(name="x")]
    try:
        oracle.capture_golden(RunnerSpec(command=["definitely-not-a-real-binary-xyz"]), cases)
    except OracleError as exc:
        assert "command not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected OracleError for a missing command")
