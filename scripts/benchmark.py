from __future__ import annotations

import time
from pathlib import Path

from app.core.graph import run_harness


def main() -> None:
    repo = Path("examples/sample_fastapi_app")
    storage = Path(".agentops/benchmark-runs.jsonl")
    started = time.perf_counter()
    record = run_harness(
        repo_path=repo,
        task="Add request logging middleware",
        storage_path=storage,
    )
    duration = time.perf_counter() - started

    print("| Metric | Value |")
    print("|---|---:|")
    print(f"| End-to-end latency | {duration:.3f}s |")
    print(f"| Validation pass rate | {int(record.test_results.passed)}/1 |")
    print(f"| Risk score | {record.risk_report.risk_score}/100 |")
    print(f"| Review findings | {len(record.review_report.findings)} |")


if __name__ == "__main__":
    main()
