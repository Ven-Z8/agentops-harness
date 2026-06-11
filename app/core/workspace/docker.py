"""DockerWorkspace — run validation in an isolated, reproducible container.

Every docker subprocess call is hard-timeout-bounded so a slow/hung daemon, image
pull, or `uv sync` becomes a fast, clear `PrepareResult(ok=False, ...)` instead of an
indefinite hang. The repo is bind-mounted (so host worker edits are visible) and deps
install to a container-only venv (no host `.venv` pollution).
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import time
import uuid
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


class DockerWorkspace:
    def __init__(
        self,
        repo_path: Path,
        image: str = DEFAULT_IMAGE,
        sync_cmd: tuple[str, ...] = ("uv", "sync"),
        smoke_cmd: tuple[str, ...] = ("uv", "run", "pytest", "--collect-only", "-q"),
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.image = image
        self.sync_cmd = list(sync_cmd)
        self.smoke_cmd = list(smoke_cmd)
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

    def run(self, argv: list[str], timeout_seconds: int) -> CommandResult:
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
