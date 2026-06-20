"""Migration-shaped probe for the OpenHands inner loop — exercise, not just construct.

The existing live smoke (`test_openhands_live_smoke.py`) proves the loop *runs* on a
one-file toy task. This probe is deliberately **migration-shaped**: a multi-file,
cross-file rename with a characterization test that pins behavior. It is the cheap,
decisive answer to "are the load-bearing components actually good, or just wired?"

What it actually exercises (vs. the audit in docs/FIRST_PRINCIPLES.md §7):
  • #1 iteration loop     — a real multi-step run, not a single edit
  • #3 skills + tools     — the worker must DISCOVER usages across files (grep/glob),
                            not just edit one named file
  • #5 inline tests       — the pinned test should be run by the worker inside the loop
  • observability         — the event log should show a non-trivial trajectory

And it demonstrates the principle the whole migration demo rests on:
  • THE ORACLE IS OWNED BY THE OUTER LAYER. We (the test = the governor) re-run the
    characterization test ourselves after the worker finishes. The worker cannot make
    us pass by weakening it — the fixture's expected outputs live here, not in the repo
    the worker edits. This is the sealed-oracle pattern in miniature.

Opt-in only: runs ONLY when OPENHANDS_LIVE_TEST is set AND an API key is present, so it
never fires in CI (no keys) or on a normal local `pytest`. Give it room to think:
    OPENHANDS_LIVE_TEST=1 OPENHANDS_MAX_ITERATIONS=30 uv run --extra dev pytest \
        tests/test_openhands_migration_probe.py -q -s
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_HAS_KEY = any(os.getenv(k) for k in ("ANTHROPIC_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (os.getenv("OPENHANDS_LIVE_TEST") and _HAS_KEY),
    reason="live probe — set OPENHANDS_LIVE_TEST=1 and provide an API key to run",
)

# ---------------------------------------------------------------------------------------
# The fixture: a tiny repo where one symbol (`legacy_add`) is used across THREE files.
# Migrating it correctly requires finding every call site (tool use) and preserving
# behavior (the characterization test must still pass). This is a mechanical migration
# in the same shape as a real one — just small enough to run in a couple of minutes.
# ---------------------------------------------------------------------------------------

_CALC_PY = '''\
"""Arithmetic core. The migration renames `legacy_add` -> `add` everywhere."""


def legacy_add(a: int, b: int) -> int:
    return a + b
'''

_SERVICE_PY = '''\
from calc import legacy_add


def running_total(values: list[int]) -> int:
    total = 0
    for v in values:
        total = legacy_add(total, v)
    return total
'''

_REPORT_PY = '''\
from calc import legacy_add


def summarize(a: int, b: int) -> str:
    return f"sum={legacy_add(a, b)}"
'''

# The characterization oracle: expected behavior, pinned by US (the outer layer).
# Crucially these expectations live in THIS file, not in the repo the worker edits.
_GOLDEN = {
    "running_total": ([1, 2, 3, 4], 10),
    "summarize": ((2, 3), "sum=5"),
}

# Task handed to the inner loop — note we name the GOAL, not the file list, so the
# worker has to discover the call sites itself (that is the point of the probe).
_TASK = (
    "Rename the function `legacy_add` to `add` throughout this repository. "
    "Update the definition and every call site and import so nothing still references "
    "`legacy_add`. Do not change any behavior. Add or run a test to confirm the "
    "arithmetic results are unchanged."
)


def _scaffold(repo: Path) -> None:
    (repo / "calc.py").write_text(_CALC_PY, encoding="utf-8")
    (repo / "service.py").write_text(_SERVICE_PY, encoding="utf-8")
    (repo / "report.py").write_text(_REPORT_PY, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )


def _changed_files(repo: Path) -> set[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _run_outer_owned_oracle(repo: Path) -> None:
    """Re-verify behavior from OUTSIDE the worker's reach (the sealed-oracle pattern).

    We import the post-migration modules and assert the golden results still hold. The
    expected values come from `_GOLDEN` in this file — the worker never saw them and
    cannot have weakened them. This is exactly how the COBOL differential oracle must
    work: the governor owns the inputs and expected outputs, not the worker.
    """
    import importlib
    import sys

    sys.path.insert(0, str(repo))
    try:
        service = importlib.import_module("service")
        report = importlib.import_module("report")
        values, expected_total = _GOLDEN["running_total"]
        assert service.running_total(values) == expected_total
        (a, b), expected_summary = _GOLDEN["summarize"]
        assert report.summarize(a, b) == expected_summary
    finally:
        sys.path.remove(str(repo))
        for mod in ("service", "report", "calc"):
            sys.modules.pop(mod, None)


def test_openhands_completes_a_multi_file_migration(tmp_path: Path) -> None:
    """The inner loop should complete a cross-file migration with behavior preserved."""
    pytest.importorskip("openhands.sdk")
    from app.core.workers.openhands_worker import OpenHandsWorker

    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold(repo)
    run_dir = tmp_path / "run"

    result = OpenHandsWorker().run(
        repo_path=repo,
        task=_TASK,
        timeout_seconds=600,
        run_dir=run_dir,
    )

    assert result.status == "completed", f"status={result.status} stderr={result.stderr[:400]}"

    # #3 tools: a real migration touches MORE THAN the one named file. If only calc.py
    # changed, the worker renamed the definition but missed the call sites — exactly the
    # cross-file discovery failure this probe exists to catch.
    changed = _changed_files(repo)
    assert "calc.py" in changed, f"definition not migrated; changed={changed}"
    assert len(changed) >= 2, (
        f"migration did not reach call sites — only changed {changed}. "
        "Cross-file tool use (grep/glob) is weak or the task under-specified."
    )

    # No reference to the old symbol should survive anywhere in the tree.
    leftover = subprocess.run(
        ["git", "grep", "-l", "legacy_add"], cwd=repo, capture_output=True, text=True
    )
    assert leftover.returncode != 0, f"`legacy_add` still present in: {leftover.stdout}"

    # The outer-owned oracle is the real verdict: behavior preserved, judged by US.
    _run_outer_owned_oracle(repo)

    # Observability (#6/#8): the run should leave a non-trivial trajectory, not the
    # 1-2 events of the toy smoke. This is a soft signal that a real loop happened.
    events_raw = (run_dir / "openhands_events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in events_raw.splitlines() if line.strip()]
    assert len(events) >= 4, f"trajectory too short to be a real migration: {len(events)} events"
