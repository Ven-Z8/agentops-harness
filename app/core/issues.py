"""Governed GitHub-issue run path.

The flagship demo of the harness thesis: take a REAL issue from a REAL
open-source repository, hand it to a governed worker (the harness plans,
enforces, validates, retries), and produce a patch + evidence bundle proving
what was attempted, what passed, and what remains.

This module owns the issue-boundary concerns only:

- fetch an issue (and its comments) via the authenticated ``gh`` CLI;
- compose the engineering task from the issue (title + body + labels);
- prepare an isolated workspace (clone at a ref, branch);
- export the resulting diff as a patch artifact with provenance.

The governed loop itself is NOT reimplemented here — ``run_harness`` owns
plan → dispatch → enforce → validate → retry → report. This module feeds it.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IssueError(RuntimeError):
    """Raised when an issue cannot be fetched or a workspace cannot be prepared."""


@dataclass(frozen=True)
class GitHubIssue:
    """A normalized GitHub issue, decoupled from GitHub's API shape."""

    owner: str
    repo: str
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    state: str
    html_url: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"

    def compose_task(self, max_body_chars: int = 6000) -> str:
        """Render the issue as an engineering task for the worker.

        The worker gets the full problem statement (title + body), the source
        URL for provenance, and explicit scope guidance. The body is truncated
        defensively; worker prompts have their own context budgets and a
        truncated-but-structured statement beats a silent one.
        """
        body = (self.body or "").strip()
        if len(body) > max_body_chars:
            body = body[:max_body_chars] + "\n\n[…issue body truncated…]"
        labels = ", ".join(self.labels) if self.labels else "none"
        lines = [
            f"Resolve GitHub issue {self.slug}: {self.title}",
            "",
            "## Issue",
            body or "(no issue body provided)",
            "",
            "## Source",
            self.html_url,
            "",
            f"## Labels\n{labels}",
            "",
            "## Scope guidance",
            "- Implement the smallest change that resolves the issue.",
            "- Add or update tests that verify the resolution.",
            "- Do not refactor unrelated code. Do not touch files outside the issue scope.",
            "- Keep the change consistent with the repository's existing conventions.",
        ]
        return "\n".join(lines)


def _run_gh(args: list[str], timeout: int = 60) -> str:
    """Run a gh CLI command and return stdout; raise IssueError on failure."""
    completed = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise IssueError(f"gh {' '.join(args[:3])} … failed: {detail[:500]}")
    return completed.stdout


def fetch_issue(owner: str, repo: str, number: int, include_comments: bool = True) -> GitHubIssue:
    """Fetch a GitHub issue via the authenticated gh CLI."""
    raw = _run_gh(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "number,title,body,labels,state,url",
        ]
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IssueError(f"gh returned non-JSON output for {owner}/{repo}#{number}: {exc}") from exc

    body = str(payload.get("body") or "")
    if include_comments:
        try:
            comments_raw = _run_gh(
                [
                    "issue",
                    "view",
                    str(number),
                    "--repo",
                    f"{owner}/{repo}",
                    "--json",
                    "comments",
                ]
            )
            comments = json.loads(comments_raw).get("comments") or []
            if comments:
                rendered = [
                    "### Comment by @"
                    f"{c.get('author', {}).get('login', 'unknown')}:\n{c.get('body', '')}"
                    for c in comments
                ]
                body += "\n\n## Issue comments\n" + "\n\n".join(rendered)
        except IssueError:
            # Comments are enrichment, not a requirement: an issue without
            # readable comments must still run, with the failure recorded.
            body += "\n\n## Issue comments\n(comment fetch failed; run without them)"

    return GitHubIssue(
        owner=owner,
        repo=repo,
        number=int(payload["number"]),
        title=str(payload.get("title") or ""),
        body=body,
        labels=tuple(str(label.get("name") or "") for label in payload.get("labels") or []),
        state=str(payload.get("state") or ""),
        html_url=str(payload.get("url") or f"https://github.com/{owner}/{repo}/issues/{number}"),
    )


def prepare_issue_workspace(
    issue: GitHubIssue,
    workspace_root: Path,
    ref: str = "HEAD",
    clone_url: str | None = None,
) -> tuple[Path, str]:
    """Clone the issue's repository into an isolated workspace and branch.

    Returns ``(repo_path, branch_name)``. The clone is a full working copy at
    ``ref``; the branch name is deterministic per issue so reruns are obvious
    in the evidence trail. Never mutates the user's existing checkout.
    ``clone_url`` overrides the GitHub HTTPS default (used by tests and
    mirrors).
    """
    workspace_root.mkdir(parents=True, exist_ok=True)
    repo_path = workspace_root / f"{issue.repo}-{issue.number}"
    if repo_path.exists():
        raise IssueError(
            f"Workspace already exists: {repo_path}. Remove it or choose another root."
        )

    url = clone_url or f"https://github.com/{issue.owner}/{issue.repo}.git"
    completed = subprocess.run(
        ["git", "clone", "--quiet", url, str(repo_path)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise IssueError(f"git clone failed: {(completed.stderr or '')[:500]}")

    if ref != "HEAD":
        checkout = subprocess.run(
            ["git", "checkout", "--quiet", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if checkout.returncode != 0:
            raise IssueError(f"git checkout {ref} failed: {(checkout.stderr or '')[:300]}")

    branch = f"agentops/issue-{issue.number}"
    branched = subprocess.run(
        ["git", "checkout", "--quiet", "-b", branch],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if branched.returncode != 0:
        raise IssueError(f"git branch failed: {(branched.stderr or '')[:300]}")

    return repo_path, branch


def export_patch(repo_path: Path, output_file: Path) -> Path:
    """Export the working-tree diff (vs HEAD) as a unified patch artifact."""
    completed = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(completed.stdout)
    return output_file


def commit_workspace_changes(repo_path: Path, message: str) -> bool:
    """Commit the worker's changes on the issue branch (for patch clarity).

    Returns True when a commit was created, False when there was nothing to
    commit. Untracked files are included — a worker's new test file is part
    of the change, not noise.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if not status.stdout.strip():
        return False
    for argv in (
        ["git", "add", "-A"],
        ["git", "-c", "user.email=agentops@local", "-c", "user.name=AgentOps Harness",
         "commit", "--quiet", "-m", message],
    ):
        subprocess.run(argv, cwd=repo_path, capture_output=True, text=True, check=False)
    return True


def quote_args(argv: list[str]) -> str:
    """Render an argv list for display in evidence artifacts."""
    return " ".join(shlex.quote(part) for part in argv)


def compose_worker_command(worker: str, repo_path: Path, task: str) -> str:
    """Render the concrete worker CLI invocation for an issue run.

    The mapping is intentionally explicit per worker: each CLI has its own
    non-interactive invocation contract, and a wrong flag silently produces a
    worker that does nothing (the exact AO-D01-03 class of failure). Unknown
    workers raise rather than guessing.
    """
    if worker == "codex":
        # codex exec: non-interactive; -s workspace-write = sandboxed edits
        # inside the workspace; -C sets the working repo; the task is the
        # positional prompt. (--full-auto is deprecated in codex ≥0.140 and
        # exits 1 with 'No such file or directory'.)
        return (
            f"codex exec -s workspace-write --skip-git-repo-check "
            f"-C {shlex.quote(str(repo_path))} {shlex.quote(task)}"
        )
    if worker == "claude":
        return (
            f"claude -p {shlex.quote(task)} --permission-mode acceptEdits "
            f"--dangerously-skip-permissions"
        )
    raise IssueError(
        f"Unknown worker {worker!r} for issue runs. Supported: codex, claude."
    )
