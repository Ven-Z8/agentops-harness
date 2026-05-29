"""Experiential memory over past runs (Code-as-Agent-Harness §3.2.3).

Storage you never read back is a log, not memory. The paper's §3.2.3 calls for
*experiential* memory: before acting on a new task, recall what happened on
similar past tasks and let those lessons shape the plan.

This module distills each run into a compact :class:`EpisodeSummary` and, given a
new task, retrieves the most similar past episodes plus the lessons they imply.

Relevance is **lexical token-overlap (Jaccard)**, not embeddings. That choice is
deliberate: it is deterministic (testable without a model), costs nothing, and is
honest about what the harness actually does — no hidden vector store to babysit.
"""

from __future__ import annotations

import re

from app.core.benchmark import ConvergenceClassifier
from app.schemas.memory import EpisodeSummary, MemoryReport, RetrievedEpisode
from app.schemas.run import RunRecord

# Words that carry no task identity — dropped before overlap scoring so that
# "Add logging to the API" matches on {add, logging, api}, not on {to, the}.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "for",
        "in",
        "on",
        "and",
        "or",
        "with",
        "into",
        "from",
        "by",
        "at",
        "is",
        "be",
        "this",
        "that",
        "it",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+")

# Episodes below this relevance are treated as "not similar" — they neither get
# returned nor contribute lessons. Without a floor, every past run would always
# be "recalled" with relevance 0, which is just the log again.
_RELEVANCE_FLOOR = 0.05


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    if not intersection:
        return 0.0
    return len(intersection) / len(a | b)


class ExperienceMemory:
    """Distills runs into episodes and recalls the ones relevant to a new task."""

    def __init__(self) -> None:
        self._classifier = ConvergenceClassifier()

    def summarize(self, record: RunRecord) -> EpisodeSummary:
        """Compress one run into a retrieval-friendly episode."""
        profile = self._classifier.classify(record)
        return EpisodeSummary(
            run_id=record.run_id,
            task=record.task,
            status=record.status,
            tests_passed=record.test_results.passed,
            risk_level=record.risk_report.risk_level,
            accepted=record.status == "completed" and not record.risk_report.blocked,
            is_implicit=profile.is_implicit,
        )

    def retrieve(
        self, task: str, records: list[RunRecord], k: int = 3
    ) -> MemoryReport:
        """Recall the ``k`` most lexically similar past episodes for ``task``."""
        query = _tokens(task)
        scored: list[RetrievedEpisode] = []
        for record in records:
            episode = self.summarize(record)
            relevance = _jaccard(query, _tokens(episode.task))
            if relevance > _RELEVANCE_FLOOR:
                scored.append(RetrievedEpisode(episode=episode, relevance=relevance))

        scored.sort(key=lambda r: r.relevance, reverse=True)
        top = scored[:k]

        return MemoryReport(
            query_task=task,
            episodes=top,
            lessons=self._lessons(top),
        )

    # -- lesson derivation ---------------------------------------------------

    def _lessons(self, episodes: list[RetrievedEpisode]) -> list[str]:
        """Turn recalled episodes into actionable, deduplicated advice."""
        lessons: list[str] = []
        seen: set[str] = set()

        def add(lesson: str) -> None:
            if lesson not in seen:
                seen.add(lesson)
                lessons.append(lesson)

        for retrieved in episodes:
            episode = retrieved.episode
            if episode.is_implicit:
                add(
                    "A similar past task converged IMPLICITLY (completed without "
                    "verification) — make sure validation commands actually run."
                )
            if episode.status == "blocked" or episode.risk_level in {
                "high",
                "critical",
            }:
                add(
                    "A similar past task was blocked on security/approval — expect a "
                    "permission or risk gate and plan for human approval."
                )
            if not episode.tests_passed and episode.status == "completed" and (
                not episode.is_implicit
            ):
                add(
                    "A similar past task had failing tests — budget time to fix them "
                    "before claiming the work is done."
                )
        return lessons
