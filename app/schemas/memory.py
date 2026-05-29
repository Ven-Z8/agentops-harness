"""Experiential-memory model (Code-as-Agent-Harness §3.2.3).

The harness already *stores* every run (JSONL + SQLite), but storage you never
read back is just a log, not memory. §3.2.3 calls for *experiential* memory:
before acting on a new task, recall what happened on similar past tasks and let
those lessons shape the plan. This module models the compact episode the harness
remembers and the report produced when it recalls relevant ones.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EpisodeSummary(BaseModel):
    """A compact, retrieval-friendly distillation of one past run."""

    run_id: str
    task: str
    status: str
    tests_passed: bool = False
    risk_level: str = "low"
    accepted: bool = False
    is_implicit: bool = False


class RetrievedEpisode(BaseModel):
    episode: EpisodeSummary
    relevance: float


class MemoryReport(BaseModel):
    query_task: str = ""
    episodes: list[RetrievedEpisode] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)

    @property
    def has_recall(self) -> bool:
        return bool(self.episodes)
