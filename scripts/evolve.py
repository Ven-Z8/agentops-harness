"""Run the Evolution Agent over stored run history (Code-as-Agent-Harness §3.5).

Reads the harness's own JSONL run log and prints structural improvement
proposals — the harness reflecting on itself. This is offline analysis: it never
mutates a repo or a run, it only reports.

Usage:
    python scripts/evolve.py [path/to/runs.jsonl]
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.core.evolution import EvolutionAgent
from app.core.storage import RunStorage


def main() -> None:
    storage_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".agentops/runs.jsonl")
    records = RunStorage(storage_path).list(limit=500)

    report = EvolutionAgent().analyze(records)
    print(EvolutionAgent().render_markdown(report))


if __name__ == "__main__":
    main()
