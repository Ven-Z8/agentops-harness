"""Schemas for the differential migration oracle.

The oracle proves behavioral equivalence between an OLD system (the source of truth)
and a NEW system (the migration) by running both on identical inputs and comparing
outputs. It is deterministic — no LLM, no worker — and the golden outputs are captured
from the old system once and then SEALED: the worker migrating the code can edit the new
system but never the golden set or the comparison. That sealing is what makes the verdict
undeniable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Normalization(BaseModel):
    """How output text is canonicalized before comparison.

    Defaults are conservative — they absorb the cosmetic differences that legitimately
    differ between, say, a COBOL fixed-width writer and a Python reimplementation
    (trailing spaces, line endings) without ever masking a real value difference.
    """

    normalize_line_endings: bool = True
    strip_trailing_whitespace: bool = True  # per line
    rstrip_final_newline: bool = True
    ignore_blank_lines: bool = False


class RunnerSpec(BaseModel):
    """How to execute one system (old or new) as a subprocess.

    ``command`` is the base argv; each case's ``args`` are appended. ``cwd`` is where the
    program runs (and where a case's input files are written). Deliberately minimal: the
    oracle shells out and reads back output — it does not know or care what language the
    system is written in. The SAME oracle works for COBOL, Python, Java, anything.
    """

    command: list[str]
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 30


class OracleCase(BaseModel):
    """One input scenario fed identically to both systems."""

    name: str
    stdin: str = ""
    args: list[str] = Field(default_factory=list)
    # Files written into cwd before the run (e.g. a fixed-width record file for a batch job).
    input_files: dict[str, str] = Field(default_factory=dict)
    # If set, the oracle captures THIS file's contents after the run instead of stdout
    # (batch jobs usually write a report file rather than printing).
    output_file: str | None = None


class GoldenCase(BaseModel):
    name: str
    output: str
    exit_code: int = 0


class GoldenSet(BaseModel):
    """The sealed source-of-truth: outputs captured from the OLD system.

    Persisted to disk and owned by the outer layer. ``verify`` only ever READS this.
    """

    captured_from: str
    normalization: Normalization = Field(default_factory=Normalization)
    cases: list[GoldenCase] = Field(default_factory=list)

    def case(self, name: str) -> GoldenCase | None:
        return next((c for c in self.cases if c.name == name), None)


class CaseResult(BaseModel):
    name: str
    equivalent: bool
    expected: str
    actual: str
    diff: str = ""
    note: str = ""


class OracleReport(BaseModel):
    """The verdict: is the new system behaviorally identical to the old one?"""

    equivalent: bool
    total: int
    passed: int
    failed: int
    cases: list[CaseResult] = Field(default_factory=list)

    def summary(self) -> str:
        head = "EQUIVALENT" if self.equivalent else "DRIFT DETECTED"
        return f"{head}: {self.passed}/{self.total} cases behaviorally identical"
