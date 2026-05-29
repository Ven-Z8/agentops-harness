"""Multi-tier permission model (Code-as-Agent-Harness §5.2.5).

The harness's first governance layer (`app/core/security.py`) is binary: an
action is either allowed or blocked. The paper argues that real governance needs
a graded middle tier — actions that should neither proceed silently nor hard
fail, but escalate to a human. This module models three tiers that mirror the
project's own policy (CLAUDE.md): "Run Freely" (auto), "Ask First" (ask), and
"Always Ask / hard stop" (deny).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PermissionTier = Literal["auto", "ask", "deny"]

# Higher number = stronger restriction. Used to pick the governing tier when many
# decisions are present: a single deny dominates; otherwise a single ask wins.
_TIER_RANK: dict[PermissionTier, int] = {"auto": 0, "ask": 1, "deny": 2}


class PermissionDecision(BaseModel):
    """One classified action and why it landed in its tier."""

    action: str
    tier: PermissionTier
    rule: str
    reason: str


class PermissionReport(BaseModel):
    decisions: list[PermissionDecision] = Field(default_factory=list)

    @property
    def highest_tier(self) -> PermissionTier:
        """The governing tier for the whole change set (deny > ask > auto)."""
        if not self.decisions:
            return "auto"
        strongest = max(_TIER_RANK[d.tier] for d in self.decisions)
        for tier, rank in _TIER_RANK.items():
            if rank == strongest:
                return tier
        return "auto"

    @property
    def blocked(self) -> bool:
        """True if any action is denied outright — the run cannot proceed."""
        return any(d.tier == "deny" for d in self.decisions)

    @property
    def needs_human(self) -> bool:
        """True if a human must confirm before proceeding (and nothing is denied)."""
        return self.highest_tier == "ask"

    def of_tier(self, tier: PermissionTier) -> list[PermissionDecision]:
        return [d for d in self.decisions if d.tier == tier]
