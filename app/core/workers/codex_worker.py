"""OpenAI Codex CLI worker — delegates tasks to `codex` as a subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.core.workers.auth_errors import detect_auth_failure
from app.prompts.workers import build_worker_prompt
from app.schemas.edit import ExternalEditResult


def _find_codex_bin() -> str | None:
    return shutil.which("codex")


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    return env


CODEX_COMMAND_STR = "codex exec --sandbox workspace-write <prompt>"


def _build_argv(codex_bin: str, prompt: str) -> list[str]:
    """Build codex CLI argv for non-interactive autonomous editing.

    `codex exec` is the non-interactive entrypoint (modern Codex CLI; the old
    `--approval-mode full-auto -q` flags were removed). `--sandbox
    workspace-write` lets the agent edit files in the repo it is run in without
    per-edit confirmation prompts, while still sandboxing shell commands.
    """
    return [codex_bin, "exec", "--sandbox", "workspace-write", prompt]


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

        prompt = build_worker_prompt(repo_path=repo_path, task=task)
        argv = _build_argv(codex_bin, prompt)
        command_str = CODEX_COMMAND_STR

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

        if completed.returncode != 0:
            auth_reason = detect_auth_failure(completed.stdout, completed.stderr)
            if auth_reason is not None:
                return ExternalEditResult(
                    status="blocked",
                    command=command_str,
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=f"{auth_reason}\n{completed.stderr}".strip(),
                    duration_seconds=duration,
                )

        return ExternalEditResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command_str,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
