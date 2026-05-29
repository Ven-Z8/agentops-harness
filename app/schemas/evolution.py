"""Harness self-improvement model (Code-as-Agent-Harness §3.5).

§3.5 describes an Evolution Agent: a component that reads the harness's own run
history and proposes improvements to the harness itself. Where experiential
memory (§3.2.3) recalls lessons for the *next task*, the Evolution Agent reflects
on the *aggregate* — recurring implicit convergence, repeated failing tests,
clustered security blocks — and turns those patterns into concrete proposals.

This module models a single proposal and the report that collects them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProposalPriority = Literal["low", "medium", "high"]


class Proposal(BaseModel):
    """A concrete, evidence-backed suggestion to improve the harness."""

    code: str
    title: str
    rationale: str
    priority: ProposalPriority = "medium"
    evidence_run_ids: list[str] = Field(default_factory=list)


class EvolutionReport(BaseModel):
    runs_analyzed: int = 0
    proposals: list[Proposal] = Field(default_factory=list)

    @property
    def has_proposals(self) -> bool:
        return bool(self.proposals)
