"""OpenAI Codex CLI worker — delegates tasks to `codex` as a subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.schemas.edit import ExternalEditResult

_PROMPT_TEMPLATE = """\
You are a coding agent working inside the repository at {repo_path}.

Task: {task}

Implement the task. Edit files as needed, run tests to verify your work, then
stop. Do not explain what you did — just make the changes and confirm with a
one-sentence summary of what changed.
"""


def _find_codex_bin() -> str | None:
    return shutil.which("codex")


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    return env


def _build_argv(codex_bin: str, prompt: str) -> list[str]:
    """Build codex CLI argv.

    --approval-mode full-auto skips per-edit confirmation prompts.
    -q suppresses spinner/progress output so stdout is clean for capture.
    """
    return [codex_bin, "--approval-mode", "full-auto", "-q", prompt]


class CodexWorker:
    """Run the OpenAI Codex CLI as a coding worker inside the harness."""

    def run(
        self,
        repo_path: Path,
        task: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
    ) -> ExternalEditResult:
        codex_bin = _find_codex_bin()
        if codex_bin is None:
            return ExternalEditResult(
                status="blocked",
                command="codex",
                stderr=(
                    "codex CLI not found on PATH. "
                    "Install: npm install -g @openai/codex"
                ),
            )

        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=codex_bin,
                stderr="Target path must be a git repository for edit attribution.",
            )

        status_lines = collect_status_lines(repo_path)
        if status_lines and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=codex_bin,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running a Codex worker."
                ),
            )

        prompt = _PROMPT_TEMPLATE.format(repo_path=repo_path, task=task)
        argv = _build_argv(codex_bin, prompt)
        command_str = "codex --approval-mode full-auto -q <prompt>"

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired as exc:
            return ExternalEditResult(
                status="failed",
                command=command_str,
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Codex worker timed out after {timeout_seconds}s.",
                duration_seconds=round(time.perf_counter() - started, 3),
            )

        duration = round(time.perf_counter() - started, 3)

        return ExternalEditResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command_str,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
