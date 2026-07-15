"""Live end-to-end smoke test for the OpenHands inner loop — the real SDK, a real LLM call.

Opt-in only: runs ONLY when OPENHANDS_LIVE_TEST is set AND an API key is present, so it
never fires by accident in CI (no keys) or on a normal local `pytest`. This is the no-mock
proof that the inner loop actually runs against the real OpenHands SDK end-to-end.

Run it with:
    OPENHANDS_LIVE_TEST=1 OPENHANDS_MAX_ITERATIONS=10 uv run --extra dev pytest \
        tests/test_openhands_live_smoke.py -q -s
(the API key is sourced from the environment / ~/.zprofile)
"""

import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.workers.openhands_config import auth_available

_HAS_KEY = auth_available(settings)

pytestmark = pytest.mark.skipif(
    not (os.getenv("OPENHANDS_LIVE_TEST") and _HAS_KEY),
    reason="live test — set OPENHANDS_LIVE_TEST=1 and provide an API key to run",
)


def test_openhands_worker_runs_a_real_loop(tmp_path: Path) -> None:
    pytest.importorskip("openhands.sdk")
    from app.core.workers.openhands_worker import OpenHandsWorker

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Sample\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )

    result = OpenHandsWorker().run(
        repo_path=repo,
        task="Create a file named hello.txt containing exactly the text: hello",
        timeout_seconds=180,
        run_dir=tmp_path / "run",
    )

    assert result.status == "completed", f"status={result.status} stderr={result.stderr[:400]}"
    # The real loop should have edited the repo (the file it was asked to create).
    assert (repo / "hello.txt").exists(), "worker did not create the requested file"
    # And the worker should have emitted observable events from the real SDK.
    events = (tmp_path / "run" / "openhands_events.jsonl").read_text(encoding="utf-8")
    assert events.strip(), "no observable SDK events were captured"
