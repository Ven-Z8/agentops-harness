"""Convergence-typed benchmark model (Code-as-Agent-Harness §4.3.2).

The paper classifies how multi-agent systems decide they are "done" into six
convergence types, and names *implicit* convergence — stopping because a loop
counter expired rather than because the work was verified — as "the most
significant gap." A raw benchmark ("latency = 0.3s, tests 1/1") argues nothing.
A convergence-typed benchmark argues something: it reports *which kind of
agreement each run actually reached*, and surfaces the runs that finished
without any real verification signal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The six convergence types named in §4.3.2, in the paper's order.
ConvergenceType = Literal[
    "correctness",
    "security",
    "performance",
    "score_based",
    "consensus",
    "implicit",
]

ALL_CONVERGENCE_TYPES: tuple[ConvergenceType, ...] = (
    "correctness",
    "security",
    "performance",
    "score_based",
    "consensus",
    "implicit",
)


class ConvergenceProfile(BaseModel):
    """How a single harness run reached (or failed to reach) a 'done' state."""

    run_id: str
    task: str
    achieved: list[ConvergenceType] = Field(default_factory=list)
    is_implicit: bool = False
    notes: list[str] = Field(default_factory=list)


class BenchmarkReport(BaseModel):
    profiles: list[ConvergenceProfile] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.profiles)

    @property
    def type_counts(self) -> dict[ConvergenceType, int]:
        counts: dict[ConvergenceType, int] = {t: 0 for t in ALL_CONVERGENCE_TYPES}
        for profile in self.profiles:
            for convergence_type in profile.achieved:
                counts[convergence_type] += 1
        return counts

    @property
    def implicit_count(self) -> int:
        return sum(1 for profile in self.profiles if profile.is_implicit)

    @property
    def implicit_rate(self) -> float:
        """The headline metric: fraction of runs that finished without a real
        verification signal. The paper's 'most significant gap' — lower is better."""
        if not self.profiles:
            return 0.0
        return self.implicit_count / self.total

    @property
    def correctness_rate(self) -> float:
        if not self.profiles:
            return 0.0
        return self.type_counts["correctness"] / self.total


class FanoutArm(BaseModel):
    """One worker's result on the shared spec: its run + convergence profile."""

    worker: str
    run_id: str
    status: str
    profile: ConvergenceProfile


class FanoutReport(BaseModel):
    """One task-spec × many workers → a convergence-typed comparison.

    Every arm ran the SAME pinned spec (same repo + base_commit), so the
    profiles are directly comparable: the report shows which workers reached
    real correctness convergence and which stopped implicitly, instead of a
    single aggregate that would hide per-worker behavior.
    """

    repo: str
    base_commit: str
    arms: list[FanoutArm] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.arms)

    @property
    def correctness_count(self) -> int:
        return sum(1 for arm in self.arms if "correctness" in arm.profile.achieved)

    @property
    def implicit_count(self) -> int:
        return sum(1 for arm in self.arms if arm.profile.is_implicit)

    @property
    def correctness_rate(self) -> float:
        if not self.arms:
            return 0.0
        return self.correctness_count / self.total

    @property
    def implicit_rate(self) -> float:
        if not self.arms:
            return 0.0
        return self.implicit_count / self.total

    @property
    def workers_reaching_correctness(self) -> list[str]:
        return [arm.worker for arm in self.arms if "correctness" in arm.profile.achieved]

    @property
    def implicit_workers(self) -> list[str]:
        return [arm.worker for arm in self.arms if arm.profile.is_implicit]

    @property
    def agreement(self) -> bool:
        """True when every arm agrees on reaching correctness (all or none).
        Mixed outcomes — some workers verifying, some not — are the signal
        the fan-out exists to surface, so agreement is False there."""
        if not self.arms:
            return False
        return self.correctness_count in (0, self.total)
