from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from app.core.security import validate_safe_command
from app.schemas.test import CommandResult, TestRunSummary


class TestRunner:
    def run(
        self,
        repo_path: Path,
        commands: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> TestRunSummary:
        selected_commands = ["python -m pytest -q"] if commands is None else commands
        results: list[CommandResult] = []

        for command in selected_commands:
            validate_safe_command(command)
            started = time.perf_counter()
            env = self._subprocess_env(repo_path)
            try:
                completed = subprocess.run(
                    self._resolve_argv(command),
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                    env=env,
                )
            except subprocess.TimeoutExpired as timed_out:
                # A hung command must be recorded as a failure, not crash the
                # run — the harness still has to produce usable evidence.
                duration = time.perf_counter() - started
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=124,
                        duration_seconds=round(duration, 3),
                        stdout=self._decode(timed_out.stdout),
                        stderr=(
                            f"Command timed out after {timeout_seconds}s and was "
                            f"terminated.\n{self._decode(timed_out.stderr)}"
                        ).strip(),
                    )
                )
                continue
            duration = time.perf_counter() - started
            results.append(
                CommandResult(
                    command=command,
                    exit_code=completed.returncode,
                    duration_seconds=round(duration, 3),
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            )

        return TestRunSummary(commands=results)

    def _decode(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _resolve_argv(self, command: str) -> list[str]:
        """Split command and replace bare 'python'/'python3' with the active interpreter."""
        parts = shlex.split(command)
        if parts and parts[0] in ("python", "python3"):
            parts[0] = sys.executable
        return parts

    def _subprocess_env(self, repo_path: Path) -> dict[str, str]:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = str(repo_path)
        return env
