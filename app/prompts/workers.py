from __future__ import annotations

from pathlib import Path


def build_worker_prompt(*, repo_path: Path, task: str) -> str:
    return f"""\
You are a coding agent working inside the repository at {repo_path}.

Task: {task}

Implement the task. Edit files as needed, run tests to verify your work, then
stop. Do not explain what you did — just make the changes and confirm with a
one-sentence summary of what changed.
"""
