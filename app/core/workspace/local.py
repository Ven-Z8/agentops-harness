from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_changed_files, collect_diff_body, collect_diff_summary
from app.schemas.test import CommandResult
from app.schemas.workspace import PrepareResult


class LocalWorkspace:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    def prepare(self) -> PrepareResult:
        return PrepareResult(ok=True)

    def run(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        started = time.perf_counter()
        try:
            c = subprocess.run(
                argv,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            return CommandResult(
                command=" ".join(argv),
                exit_code=124,
                duration_seconds=round(time.perf_counter() - started, 3),
                stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                stderr=f"timed out after {timeout_seconds}s",
            )
        return CommandResult(
            command=" ".join(argv),
            exit_code=c.returncode,
            duration_seconds=round(time.perf_counter() - started, 3),
            stdout=c.stdout,
            stderr=c.stderr,
        )

    def read_changes(self) -> tuple[list[str], str, str]:
        # Exactly today's behavior — no augmentation — so routing diff collection
        # through the workspace is a zero-behavior-change refactor.
        return (
            collect_changed_files(self.repo_path),
            collect_diff_summary(self.repo_path),
            collect_diff_body(self.repo_path),
        )

    def cleanup(self) -> None:
        return None
