from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.core.security import validate_safe_command
from app.schemas.test import CommandResult, TestRunSummary

# Cold `uv run pytest` can spend over a minute resolving/building the
# environment before tests even start, so the default is generous.
DEFAULT_TIMEOUT_SECONDS = 300


class TestRunner:
    def run(
        self,
        repo_path: Path,
        commands: list[str] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> TestRunSummary:
        selected_commands = ["python -m pytest -q"] if commands is None else commands
        results: list[CommandResult] = []

        for command in selected_commands:
            validate_safe_command(command)
            started = time.perf_counter()
            env = self._subprocess_env(repo_path)
            # Run in a new session/process group so that on timeout we can kill
            # the whole tree (e.g. uv -> pytest -> workers), not just the direct
            # child — otherwise grandchildren leak as orphans.
            process = subprocess.Popen(
                self._resolve_argv(command),
                cwd=repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                # A hung command must be recorded as a failure, not crash the
                # run — the harness still has to produce usable evidence.
                self._kill_process_group(process)
                stdout, stderr = process.communicate()
                duration = time.perf_counter() - started
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=124,
                        duration_seconds=round(duration, 3),
                        stdout=self._decode(stdout),
                        stderr=(
                            f"Command timed out after {timeout_seconds}s and the "
                            f"process group was terminated.\n{self._decode(stderr)}"
                        ).strip(),
                    )
                )
                continue
            duration = time.perf_counter() - started
            results.append(
                CommandResult(
                    command=command,
                    exit_code=exit_code,
                    duration_seconds=round(duration, 3),
                    stdout=self._decode(stdout),
                    stderr=self._decode(stderr),
                )
            )

        return TestRunSummary(commands=results)

    def _kill_process_group(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()

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
