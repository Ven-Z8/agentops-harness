"""Deterministic scripted-edit worker — makes a file edit with no model call.

Used as a CI worker and as a live-demo safety net: it exercises the full
"AgentOps governs a worker" loop (clean-repo attribution, diff, tests, guards,
product review) without any provider call. Invoked through the existing
``--worker-command`` path, e.g. ``agentops-scripted-edit NOTES.md "hello"``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: agentops-scripted-edit <path> <content>")
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sys.argv[2] + "\n", encoding="utf-8")
