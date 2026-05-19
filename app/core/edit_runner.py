from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.core.security import validate_safe_command
from app.schemas.edit import ExternalEditResult


def render_worker_command(command_template: str, repo_path: Path, task: str) -> list[str]:
    rendered = command_template.format(
        repo_path=shlex.quote(str(repo_path)),
        task=shlex.quote(task),
    )
    validate_safe_command(rendered)
    return shlex.split(rendered)


class ExternalWorkerRunner:
    def run(
        self,
        repo_path: Path,
        task: str,
        command_template: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
    ) -> ExternalEditResult:
        argv = render_worker_command(command_template, repo_path=repo_path, task=task)
        command = " ".join(shlex.quote(part) for part in argv)

        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=command,
                stderr="Target path must be a git repository for edit attribution.",
            )

        status_lines = collect_status_lines(repo_path)
        if status_lines and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=command,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running an external worker."
                ),
            )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExternalEditResult(
                status="failed",
                command=command,
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Worker timed out after {timeout_seconds}s.",
                duration_seconds=round(time.perf_counter() - started, 3),
            )

        return ExternalEditResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=round(time.perf_counter() - started, 3),
        )
