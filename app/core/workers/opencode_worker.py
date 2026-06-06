"""OpenCode CLI worker - delegates tasks to `opencode` as a subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.prompts.workers import build_worker_prompt
from app.schemas.edit import ExternalEditResult


def _find_opencode_bin() -> str | None:
    """Return the absolute path to `opencode`, including Bun's default bin dir."""
    found = shutil.which("opencode")
    if found:
        return found
    bun_bin = Path.home() / ".bun" / "bin" / "opencode"
    if bun_bin.exists():
        return str(bun_bin)
    return None


def _subprocess_env() -> dict[str, str]:
    """Build env for the opencode subprocess.

    Bun installs global binaries into ~/.bun/bin by default. GUI-launched apps
    often miss shell PATH customizations, so make that path explicit here.
    """
    env = os.environ.copy()
    bun_bin = str(Path.home() / ".bun" / "bin")
    current_path = env.get("PATH", "")
    if bun_bin not in current_path.split(os.pathsep):
        env["PATH"] = bun_bin + os.pathsep + current_path
    return env


def _build_argv(opencode_bin: str, repo_path: Path, prompt: str) -> list[str]:
    """Build OpenCode CLI argv.

    OPENCODE_MODEL is optional. When set, use values like
    `openrouter/moonshotai/kimi-k2`; otherwise OpenCode uses its configured
    default model.
    """
    argv = [
        opencode_bin,
        "run",
        "--dir",
        str(repo_path),
        "--dangerously-skip-permissions",
    ]
    model = os.environ.get("OPENCODE_MODEL", "").strip()
    if model:
        argv.extend(["--model", model])
    argv.append(prompt)
    return argv


class OpenCodeWorker:
    """Run the OpenCode CLI as a coding worker inside the harness."""

    def run(
        self,
        repo_path: Path,
        task: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
    ) -> ExternalEditResult:
        opencode_bin = _find_opencode_bin()
        if opencode_bin is None:
            return ExternalEditResult(
                status="blocked",
                command="opencode",
                stderr=(
                    "opencode CLI not found on PATH or ~/.bun/bin. "
                    "Install: bun add -g opencode-ai"
                ),
            )

        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=opencode_bin,
                stderr="Target path must be a git repository for edit attribution.",
            )

        status_lines = collect_status_lines(repo_path)
        if status_lines and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=opencode_bin,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running an OpenCode worker."
                ),
            )

        prompt = build_worker_prompt(repo_path=repo_path, task=task)
        argv = _build_argv(opencode_bin, repo_path, prompt)
        model_flag = " --model <OPENCODE_MODEL>" if os.environ.get("OPENCODE_MODEL") else ""
        command_str = f"opencode run --dir <repo>{model_flag} <prompt>"

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
                stderr=exc.stderr or f"OpenCode worker timed out after {timeout_seconds}s.",
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
