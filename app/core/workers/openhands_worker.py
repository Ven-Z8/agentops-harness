"""OpenHands SDK worker — runs a real OpenHands agent loop as a subprocess.

Follows the slide-16 six-step SDK pattern (workspace -> agent -> conversation ->
run -> extract diff) against the real OpenHands SDK 1.28 API. The agent runs in a
child process (`app.core.workers.openhands_runner`) so the heavy import is lazy and
the run is timeout-bounded, exactly like the CLI workers. The worker edits the repo
in place; the harness reads the diff (step 6) via its existing collect_diff node.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.core.workers.auth_errors import detect_auth_failure
from app.prompts.workers import build_worker_prompt
from app.schemas.edit import ExternalEditResult

COMMAND_STR = "python -m app.core.workers.openhands_runner <repo> (task on stdin)"


class OpenHandsWorker:
    """Run an OpenHands SDK agent over a repository inside the harness."""

    def run(
        self,
        repo_path: Path,
        task: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
        workspace: str = "local",
    ) -> ExternalEditResult:
        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=COMMAND_STR,
                stderr="Target path must be a git repository for edit attribution.",
            )

        if collect_status_lines(repo_path) and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=COMMAND_STR,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running an OpenHands worker."
                ),
            )

        prompt = build_worker_prompt(repo_path=repo_path, task=task)
        argv = [sys.executable, "-m", "app.core.workers.openhands_runner", str(repo_path)]
        # Select the OpenHands workspace mode (local in-process loop, or its own Docker
        # agent-server container) for the runner subprocess.
        env = os.environ.copy()
        env["OPENHANDS_WORKSPACE"] = "docker" if workspace == "docker" else "local"

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return ExternalEditResult(
                status="failed",
                command=COMMAND_STR,
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"OpenHands worker timed out after {timeout_seconds}s.",
                duration_seconds=round(time.perf_counter() - started, 3),
            )

        duration = round(time.perf_counter() - started, 3)
        code = completed.returncode

        # Auth (exit 3) and missing-SDK (exit 4) are setup problems, not run failures.
        if code in (3, 4) or detect_auth_failure(completed.stdout, completed.stderr):
            reason = (
                "OpenHands SDK not installed. Install: uv sync --extra openhands."
                if code == 4
                else detect_auth_failure(completed.stdout, completed.stderr)
                or "OpenHands authentication failed; set ANTHROPIC_API_KEY and retry."
            )
            return ExternalEditResult(
                status="blocked",
                command=COMMAND_STR,
                exit_code=code,
                stdout=completed.stdout,
                stderr=f"{reason}\n{completed.stderr}".strip(),
                duration_seconds=duration,
            )

        return ExternalEditResult(
            status="completed" if code == 0 else "failed",
            command=COMMAND_STR,
            exit_code=code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
