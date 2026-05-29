"""Cross-artifact conflict model (Code-as-Agent-Harness §5.2.3).

A harness run emits several artifacts — a plan, a diff, test results, a written
report, an evidence check, and security gates. Each is produced by a different
agent, so they can silently *disagree*: a report that claims "all tests pass"
while the test summary shows a failure, or a "ready to merge" report when a
security gate actually blocked the change.

§5.2.3 calls for a conflict policy that surfaces these contradictions instead of
shipping them. This module models the contradictions the auditor can find.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConflictSeverity = Literal["info", "warning", "critical"]


class Conflict(BaseModel):
    """One detected contradiction between two or more artifacts."""

    code: str
    severity: ConflictSeverity
    message: str
    sources: list[str] = Field(default_factory=list)


class ConflictReport(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def is_consistent(self) -> bool:
        """True when no *critical* contradiction was found."""
        return not any(c.severity == "critical" for c in self.conflicts)

    def of_severity(self, severity: ConflictSeverity) -> list[Conflict]:
        return [c for c in self.conflicts if c.severity == severity]
