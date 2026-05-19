"""Claude Code CLI worker — delegates tasks to `claude` as a subprocess."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from app.core.git_utils import collect_status_lines, is_git_repo
from app.schemas.edit import ExternalEditResult

# Tools a coding worker needs; excludes agent-management tools.
_CODING_TOOLS = "Read,Edit,Write,Bash,Glob,Grep"

# Prompt template handed to claude CLI. Keeps the instruction compact so
# the worker focuses on the repo rather than re-explaining the harness.
_PROMPT_TEMPLATE = """\
You are a coding agent working inside the repository at {repo_path}.

Task: {task}

Implement the task. Edit files as needed, run tests to verify your work, then
stop. Do not explain what you did — just make the changes and confirm with a
one-sentence summary of what changed.
"""


def _find_claude_bin() -> str | None:
    """Return the absolute path to the `claude` CLI, or None if not found."""
    return shutil.which("claude")


def _subprocess_env() -> dict[str, str]:
    """Build env for the claude subprocess.

    CLAUDECODE="" signals that a parent Claude Code session exists, which
    prevents the child process from hitting the session-lock check.
    """
    env = os.environ.copy()
    env["CLAUDECODE"] = ""
    return env


def _build_argv(claude_bin: str, prompt: str, allowed_tools: str) -> list[str]:
    """Build the claude CLI argv.

    Uses --bare when ANTHROPIC_API_KEY is available (fastest, most isolated).
    Falls back to standard mode (keychain/OAuth) otherwise.
    --dangerously-skip-permissions is required for non-interactive file editing.
    """
    argv = [claude_bin, "--output-format", "json", "--dangerously-skip-permissions",
            "--allowedTools", allowed_tools, "-p", prompt]
    if os.environ.get("ANTHROPIC_API_KEY"):
        argv.insert(1, "--bare")
    return argv


class ClaudeCodeWorker:
    """Run the Claude Code CLI as a coding worker inside the harness."""

    def run(
        self,
        repo_path: Path,
        task: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
        allowed_tools: str = _CODING_TOOLS,
    ) -> ExternalEditResult:
        claude_bin = _find_claude_bin()
        if claude_bin is None:
            return ExternalEditResult(
                status="blocked",
                command="claude",
                stderr=(
                    "claude CLI not found on PATH. "
                    "Install Claude Code: https://claude.ai/claude-code"
                ),
            )

        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=claude_bin,
                stderr="Target path must be a git repository for edit attribution.",
            )

        status_lines = collect_status_lines(repo_path)
        if status_lines and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=claude_bin,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running a Claude Code worker."
                ),
            )

        prompt = _PROMPT_TEMPLATE.format(repo_path=repo_path, task=task)
        argv = _build_argv(claude_bin, prompt, allowed_tools)
        bare_flag = "--bare " if "--bare" in argv else ""
        command_str = f"claude {bare_flag}-p <prompt> --allowedTools {allowed_tools}"

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
                stderr=exc.stderr or f"Claude Code worker timed out after {timeout_seconds}s.",
                duration_seconds=round(time.perf_counter() - started, 3),
            )

        duration = round(time.perf_counter() - started, 3)

        # claude --output-format json emits a JSON envelope; extract .result
        stdout = completed.stdout
        parsed_result = _extract_result(stdout)

        return ExternalEditResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command_str,
            exit_code=completed.returncode,
            stdout=parsed_result or stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )


def _extract_result(raw: str) -> str:
    """Parse claude --output-format json stdout and return the result text."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        return data.get("result", raw)
    except json.JSONDecodeError:
        # Non-JSON output (older CLI version or bare text) — return as-is.
        return raw
