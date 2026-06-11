"""DockerWorkspace — run validation in an isolated, reproducible container.

Every docker subprocess call is hard-timeout-bounded so a slow/hung daemon, image
pull, or `uv sync` becomes a fast, clear `PrepareResult(ok=False, ...)` instead of an
indefinite hang.

Two isolation modes:
  - ``isolation="validation"`` (default): the repo is bind-mounted (host worker edits are
    visible); deps install to a container-only venv (no host ``.venv`` pollution).
  - ``isolation="full"``: the repo is COPIED into the container (no bind-mount); the worker
    runs inside via ``run_worker()``; only permitted changed files are extracted back to the
    host via ``extract_permitted()``.  Denied changes die with the container.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app.schemas.test import CommandResult
from app.schemas.workspace import PrepareResult

DEFAULT_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
DAEMON_TIMEOUT = 15
IMAGE_INSPECT_TIMEOUT = 20
IMAGE_PULL_TIMEOUT = 300
CONTROL_OP_TIMEOUT = 60
SYNC_TIMEOUT = 300
CONTAINER_TTL = "3600"
CONTAINER_VENV = "/opt/agentops-venv"

# Timeout for a single docker cp extraction of one file.
CP_FILE_TIMEOUT = 30
# Timeout for git-archive piped into the container.
GIT_ARCHIVE_TIMEOUT = 60
# Timeout for git init / add / commit inside the container (baseline snapshot).
GIT_BASELINE_TIMEOUT = 60


class DockerWorkspace:
    def __init__(
        self,
        repo_path: Path,
        image: str = DEFAULT_IMAGE,
        sync_cmd: tuple[str, ...] = ("uv", "sync"),
        smoke_cmd: tuple[str, ...] = ("uv", "run", "pytest", "--collect-only", "-q"),
        isolation: str = "validation",
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.image = image
        self.sync_cmd = list(sync_cmd)
        self.smoke_cmd = list(smoke_cmd)
        self.isolation = isolation
        self.container_id: str | None = None

    def _docker(self, args: list[str], timeout: int, stdin: bytes | None = None):
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=stdin is None,
            input=stdin,
            timeout=timeout,
            check=False,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(self) -> PrepareResult:
        if shutil.which("docker") is None:
            return PrepareResult(ok=False, diagnostic="docker CLI not found on PATH")
        try:
            if self._docker(["info"], timeout=DAEMON_TIMEOUT).returncode != 0:
                return PrepareResult(ok=False, diagnostic="docker daemon not available")
        except subprocess.TimeoutExpired:
            return PrepareResult(ok=False, diagnostic="docker daemon unresponsive (info timed out)")

        pull = self._ensure_image()
        if pull is not None:
            return pull

        if self.isolation == "full":
            return self._prepare_full_isolation()
        return self._prepare_validation()

    def run(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        """Run a command inside the container (validation-mode alias; usable in full mode too)."""
        command = " ".join(argv)
        if self.container_id is None:
            return CommandResult(
                command=command, exit_code=125, duration_seconds=0.0,
                stdout="", stderr="workspace container not prepared",
            )
        started = time.perf_counter()
        try:
            c = self._docker(
                ["exec", "-w", "/workspace", self.container_id, *argv],
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                command=command, exit_code=124,
                duration_seconds=round(time.perf_counter() - started, 3),
                stdout="", stderr=f"timed out after {timeout_seconds}s",
            )
        return CommandResult(
            command=command, exit_code=c.returncode,
            duration_seconds=round(time.perf_counter() - started, 3),
            stdout=c.stdout, stderr=c.stderr,
        )

    def run_worker(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        """Run the worker command inside the sandbox container (full-isolation mode).

        Semantically identical to ``run()`` but named explicitly for the sandbox path
        so callers can distinguish worker execution from test/smoke commands.
        """
        return self.run(argv, timeout_seconds)

    def extract_permitted(
        self,
        is_denied: Callable[[str], bool],
    ) -> tuple[list[str], list[str]]:
        """Extract changed files from the container to the host, skipping denied paths.

        Runs ``git status --porcelain`` inside the container to enumerate
        added/modified files.  For each file:
        - If ``is_denied(path)`` is True → skip it (recorded as *blocked*).
        - Otherwise → ``docker cp`` the file to the host repo and record as *extracted*.

        Returns ``(extracted, blocked)`` path lists.
        All docker ops are bounded by module-level timeouts.
        """
        if self.container_id is None:
            return ([], [])

        status = self.run(["git", "status", "--porcelain"], timeout_seconds=CONTROL_OP_TIMEOUT)
        extracted: list[str] = []
        blocked: list[str] = []

        for raw_line in status.stdout.splitlines():
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue
            # git status --porcelain: 2-char status code + space + path
            # Handle rename "R old -> new" as well as plain added/modified.
            xy = raw_line[:2]
            rest = raw_line[3:]

            # For renames (R) the format is "old -> new"; take the destination.
            path = rest.split(" -> ", 1)[1].strip() if " -> " in rest else rest.strip().strip('"')

            # Only extract added (A, ??) or modified (M) files; skip deletions (D).
            if xy.strip() in {"D", "DD"}:
                continue
            if not path:
                continue

            if is_denied(path):
                blocked.append(path)
                continue

            # Ensure the parent directory exists on the host.
            host_dest = self.repo_path / path
            host_dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                cp = self._docker(
                    ["cp", f"{self.container_id}:/workspace/{path}", str(host_dest)],
                    timeout=CP_FILE_TIMEOUT,
                )
                if cp.returncode == 0:
                    extracted.append(path)
                # If cp fails (e.g. path doesn't exist in container), silently skip.
            except subprocess.TimeoutExpired:
                # A single file copy timed out — skip it rather than hanging.
                pass

        return (extracted, blocked)

    def read_changes(self) -> tuple[list[str], str, str]:
        if self.container_id is None:
            return ([], "", "")
        status = self.run(["git", "status", "--porcelain"], timeout_seconds=CONTROL_OP_TIMEOUT)
        changed = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]
        summary = self.run(["git", "diff", "--stat"], timeout_seconds=CONTROL_OP_TIMEOUT).stdout
        body = self.run(["git", "diff"], timeout_seconds=CONTROL_OP_TIMEOUT).stdout
        return (changed, summary, body)

    def cleanup(self) -> None:
        if self.container_id is None:
            return
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._docker(["rm", "-f", self.container_id], timeout=CONTROL_OP_TIMEOUT)
        self.container_id = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_validation(self) -> PrepareResult:
        """Bind-mount prepare: original validation-mode behaviour."""
        name = f"agentops-ws-{uuid.uuid4().hex[:8]}"
        try:
            run = self._docker(
                [
                    "run", "-d", "--name", name,
                    "-v", f"{self.repo_path}:/workspace",
                    "-w", "/workspace",
                    "-e", f"UV_PROJECT_ENVIRONMENT={CONTAINER_VENV}",
                    self.image, "sleep", CONTAINER_TTL,
                ],
                timeout=CONTROL_OP_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return PrepareResult(ok=False, diagnostic="docker run (start container) timed out")
        if run.returncode != 0:
            return PrepareResult(ok=False, diagnostic=f"docker run failed: {run.stderr[-500:]}")
        self.container_id = run.stdout.strip()

        try:
            sync = self._docker(
                ["exec", self.container_id, *self.sync_cmd], timeout=SYNC_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            self.cleanup()
            return PrepareResult(
                ok=False, diagnostic=f"{' '.join(self.sync_cmd)} timed out after {SYNC_TIMEOUT}s"
            )
        if sync.returncode != 0:
            diagnostic = f"{' '.join(self.sync_cmd)} failed: {sync.stderr[-800:]}"
            self.cleanup()
            return PrepareResult(
                ok=False,
                diagnostic=diagnostic,
                smoke_command=" ".join(self.sync_cmd),
                smoke_exit_code=sync.returncode,
            )

        try:
            smoke = self._docker(
                ["exec", self.container_id, *self.smoke_cmd], timeout=CONTROL_OP_TIMEOUT
            )
            smoke_exit: int | None = smoke.returncode
        except subprocess.TimeoutExpired:
            smoke_exit = 124
        return PrepareResult(
            ok=True, smoke_command=" ".join(self.smoke_cmd), smoke_exit_code=smoke_exit
        )

    def _prepare_full_isolation(self) -> PrepareResult:
        """Full-isolation prepare: copy-in the repo, no bind-mount, baseline git commit."""
        name = f"agentops-sandbox-{uuid.uuid4().hex[:8]}"

        # 1. Start the container with NO bind-mount.
        try:
            run = self._docker(
                [
                    "run", "-d", "--name", name,
                    "-w", "/workspace",
                    "-e", f"UV_PROJECT_ENVIRONMENT={CONTAINER_VENV}",
                    self.image, "sleep", CONTAINER_TTL,
                ],
                timeout=CONTROL_OP_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return PrepareResult(ok=False, diagnostic="docker run (sandbox) timed out")
        if run.returncode != 0:
            return PrepareResult(
                ok=False, diagnostic=f"docker run (sandbox) failed: {run.stderr[-500:]}"
            )
        self.container_id = run.stdout.strip()

        # 2. Ensure git is available in the container (the slim uv image ships without it).
        #    First check; if missing, install via apt-get.
        GIT_INSTALL_TIMEOUT = 120
        try:
            git_check = self._docker(
                ["exec", self.container_id, "sh", "-c", "which git || command -v git"],
                timeout=CONTROL_OP_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.cleanup()
            return PrepareResult(ok=False, diagnostic="git check in container timed out")

        if git_check.returncode != 0:
            # git not found — install it.
            try:
                apt = self._docker(
                    [
                        "exec", self.container_id,
                        "sh", "-c",
                        "apt-get update -qq && apt-get install -y -qq git",
                    ],
                    timeout=GIT_INSTALL_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                self.cleanup()
                return PrepareResult(ok=False, diagnostic="apt-get install git timed out")
            if apt.returncode != 0:
                self.cleanup()
                return PrepareResult(
                    ok=False, diagnostic=f"apt-get install git failed: {apt.stderr[-300:]}"
                )

        # 3. Create /workspace directory inside the container.
        try:
            mkdir = self._docker(
                ["exec", self.container_id, "mkdir", "-p", "/workspace"],
                timeout=CONTROL_OP_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.cleanup()
            return PrepareResult(ok=False, diagnostic="mkdir /workspace in container timed out")
        if mkdir.returncode != 0:
            self.cleanup()
            return PrepareResult(
                ok=False, diagnostic=f"mkdir /workspace failed: {mkdir.stderr[-300:]}"
            )

        # 5. Copy repo into container via git archive | docker exec tar.
        #    We use a two-process pipeline: git archive on the host piped to docker exec tar.
        try:
            git_archive = subprocess.Popen(
                ["git", "-C", str(self.repo_path), "archive", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            tar_extract = subprocess.Popen(
                ["docker", "exec", "-i", self.container_id, "tar", "-x", "-C", "/workspace"],
                stdin=git_archive.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Allow git_archive stdout to be consumed by tar_extract.
            if git_archive.stdout:
                git_archive.stdout.close()

            _, tar_err = tar_extract.communicate(timeout=GIT_ARCHIVE_TIMEOUT)
            git_archive.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                git_archive.kill()
            with contextlib.suppress(Exception):
                tar_extract.kill()
            self.cleanup()
            return PrepareResult(ok=False, diagnostic="git archive | tar copy-in timed out")
        except Exception as exc:  # noqa: BLE001
            self.cleanup()
            return PrepareResult(ok=False, diagnostic=f"git archive | tar copy-in failed: {exc}")

        if tar_extract.returncode != 0:
            self.cleanup()
            diag = f"tar copy-in failed (exit {tar_extract.returncode}): {tar_err.decode()[-300:]}"
            return PrepareResult(ok=False, diagnostic=diag)

        # 6. Baseline git commit inside the container so we can diff against it later.
        baseline_cmds: list[tuple[list[str], int, str]] = [
            (["git", "init"], GIT_BASELINE_TIMEOUT, "git init in container"),
            (
                ["git", "-c", "user.email=sandbox@agentops", "-c", "user.name=sandbox",
                 "add", "-A"],
                GIT_BASELINE_TIMEOUT,
                "git add -A in container",
            ),
            (
                ["git", "-c", "user.email=sandbox@agentops", "-c", "user.name=sandbox",
                 "commit", "-m", "base"],
                GIT_BASELINE_TIMEOUT,
                "git commit base in container",
            ),
        ]
        for cmd, t, label in baseline_cmds:
            try:
                result = self._docker(
                    ["exec", "-w", "/workspace", self.container_id, *cmd], timeout=t
                )
            except subprocess.TimeoutExpired:
                self.cleanup()
                return PrepareResult(ok=False, diagnostic=f"{label} timed out")
            if result.returncode != 0:
                self.cleanup()
                return PrepareResult(
                    ok=False,
                    diagnostic=f"{label} failed (exit {result.returncode}): {result.stderr[-300:]}",
                )

        # 7. uv sync (install deps inside container).
        try:
            sync = self._docker(
                ["exec", "-w", "/workspace", self.container_id, *self.sync_cmd],
                timeout=SYNC_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.cleanup()
            sync_label = " ".join(self.sync_cmd)
            return PrepareResult(
                ok=False, diagnostic=f"{sync_label} (sandbox) timed out after {SYNC_TIMEOUT}s"
            )
        if sync.returncode != 0:
            diagnostic = f"{' '.join(self.sync_cmd)} (sandbox) failed: {sync.stderr[-800:]}"
            self.cleanup()
            return PrepareResult(
                ok=False,
                diagnostic=diagnostic,
                smoke_command=" ".join(self.sync_cmd),
                smoke_exit_code=sync.returncode,
            )

        # 8. Smoke check.
        try:
            smoke = self._docker(
                ["exec", "-w", "/workspace", self.container_id, *self.smoke_cmd],
                timeout=CONTROL_OP_TIMEOUT,
            )
            smoke_exit: int | None = smoke.returncode
        except subprocess.TimeoutExpired:
            smoke_exit = 124
        return PrepareResult(
            ok=True, smoke_command=" ".join(self.smoke_cmd), smoke_exit_code=smoke_exit
        )

    def _ensure_image(self) -> PrepareResult | None:
        try:
            present = self._docker(
                ["image", "inspect", self.image], timeout=IMAGE_INSPECT_TIMEOUT
            )
            if present.returncode == 0:
                return None
            pull = self._docker(["pull", self.image], timeout=IMAGE_PULL_TIMEOUT)
            if pull.returncode != 0:
                return PrepareResult(
                    ok=False, diagnostic=f"docker pull failed: {pull.stderr[-500:]}"
                )
            return None
        except subprocess.TimeoutExpired:
            return PrepareResult(ok=False, diagnostic="docker image pull/inspect timed out")
