"""Verification stack with explicit scope (Code-as-Agent-Harness §5.2.2).

The paper argues that a single pass/fail signal breeds overconfidence: "a green
test is not the full specification." Instead, every accepted action should carry
an *evidence bundle* in which each verifier declares what it verifies, what it
cannot verify, and the confidence it provides — plus the regions left untested
and the risks that remain.

This module models that bundle. It does not run new checks; it consolidates the
outputs of the verifiers the harness already runs (tests, reviewer, risk guard,
evidence guard) into one inspectable artifact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerifierVerdict = Literal["pass", "warn", "fail", "not_run"]
Confidence = Literal["low", "medium", "high"]

_CONFIDENCE_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}


class VerifierScope(BaseModel):
    """One verifier's result together with the explicit scope of what it covers."""

    name: str
    verdict: VerifierVerdict
    confidence: Confidence
    verifies: str
    cannot_verify: str
    detail: str = ""


class VerificationBundle(BaseModel):
    """The composed evidence bundle attached to a run (§5.2.2)."""

    checks: list[VerifierScope] = Field(default_factory=list)
    untested_regions: list[str] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """True when no verifier failed. A bundle can be accepted yet incomplete."""
        return all(check.verdict != "fail" for check in self.checks)

    @property
    def overall_confidence(self) -> Confidence:
        """The weakest confidence among verifiers that actually ran.

        Following the paper's epistemic stance: the bundle is only as trustworthy
        as its least-confident contributing signal.
        """
        ran = [c for c in self.checks if c.verdict != "not_run"]
        if not ran:
            return "low"
        weakest = min(_CONFIDENCE_RANK[c.confidence] for c in ran)
        for name, rank in _CONFIDENCE_RANK.items():
            if rank == weakest:
                return name
        return "low"
