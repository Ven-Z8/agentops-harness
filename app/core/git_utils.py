from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(repo_path: Path) -> bool:
    return git_top_level(repo_path) == repo_path.resolve()


def git_top_level(repo_path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )


def collect_status_lines(repo_path: Path) -> list[str]:
    if not is_git_repo(repo_path):
        return []

    result = run_git(repo_path, ["status", "--porcelain"])
    return [line for line in result.stdout.splitlines() if line]


def is_worktree_clean(repo_path: Path) -> bool:
    return not collect_status_lines(repo_path)


_NOISE_DIR_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
}
_NOISE_SUFFIXES = (".pyc", ".pyo")
_NOISE_NAMES = {".DS_Store"}


def is_ephemeral_path(path: str) -> bool:
    """True for build/cache artifacts that should not be attributed to a worker."""
    posix = path.replace("\\", "/").rstrip("/")
    parts = posix.split("/")
    name = parts[-1] if parts else posix
    if _NOISE_DIR_PARTS.intersection(parts):
        return True
    # An `*.egg-info` component anywhere covers the dir AND every file nested inside it
    # (PKG-INFO, SOURCES.txt, ...), not just the directory entry.
    if any(part.endswith(".egg-info") for part in parts):
        return True
    if name in _NOISE_NAMES:
        return True
    return name.endswith(_NOISE_SUFFIXES)


def collect_changed_files(repo_path: Path) -> list[str]:
    if not is_git_repo(repo_path):
        return []

    changed: list[str] = []
    for line in collect_status_lines(repo_path):
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", maxsplit=1)[1]
        if is_ephemeral_path(path):
            continue
        changed.append(path)
    return sorted(set(changed))


def collect_deleted_files(repo_path: Path) -> list[str]:
    if not is_git_repo(repo_path):
        return []

    result = run_git(repo_path, ["diff", "--name-only", "--diff-filter=D"])
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def collect_diff_summary(repo_path: Path) -> str:
    if not is_git_repo(repo_path):
        return "Repository is not a git worktree; no diff summary available."

    stat = run_git(repo_path, ["diff", "--stat"])
    if stat.stdout.strip():
        return stat.stdout.strip()
    return "No working tree diff detected."


def collect_diff_body(repo_path: Path, max_chars: int = 20000) -> str:
    """Return the working-tree diff body (not just the --stat summary).

    Used to judge whether changes actually satisfy intent — the --stat summary
    only lists file names, so a claim like "/healthz endpoint added" can only be
    verified against the diff body. Capped to keep the haystack bounded.
    """
    if not is_git_repo(repo_path):
        return ""
    body = run_git(repo_path, ["diff"]).stdout
    return body[:max_chars]
