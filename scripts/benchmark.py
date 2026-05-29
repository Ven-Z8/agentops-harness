"""Convergence-typed benchmark runner (Code-as-Agent-Harness §4.3.2).

Runs the harness over a small set of scenarios and reports *which convergence
type* each run reached — instead of raw latency/pass numbers that argue nothing.
Includes a deliberately un-gated scenario (no validation commands) to show the
harness correctly flagging the paper's "implicit convergence" gap.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.core.benchmark import ConvergenceClassifier, summarize_benchmark
from app.core.graph import run_harness

SCENARIOS: list[dict] = [
    {
        "task": "Add request logging middleware",
        "test_commands": ["python -m pytest -q"],
    },
    # No validation commands: should be flagged as implicit convergence.
    {
        "task": "Tweak a docstring",
        "test_commands": [],
    },
]


def main() -> None:
    repo = Path("examples/sample_fastapi_app")
    storage = Path(".agentops/benchmark-runs.jsonl")
    classifier = ConvergenceClassifier()

    profiles = []
    started = time.perf_counter()
    for scenario in SCENARIOS:
        record = run_harness(
            repo_path=repo,
            task=scenario["task"],
            storage_path=storage,
            test_commands=scenario["test_commands"] or None,
        )
        profiles.append(classifier.classify(record))
    duration = time.perf_counter() - started

    report = summarize_benchmark(profiles)
    print(classifier.render_markdown(report))
    print(f"\n_Total wall time for {report.total} runs: {duration:.3f}s_")


if __name__ == "__main__":
    main()
