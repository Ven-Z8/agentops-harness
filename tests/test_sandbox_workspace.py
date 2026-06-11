"""Phase 2 sandbox (full-isolation) tests.

All tests in this module require a running Docker daemon and are auto-skipped when
one is absent.  Every docker call inside DockerWorkspace is timeout-bounded so
these tests cannot hang the suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.security import is_sensitive_path
from app.core.workspace.docker import DockerWorkspace


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_up(), reason="docker daemon not available")

# A minimal pyproject.toml that makes uv sync (and git archive) work inside the
# container without pulling any real Python packages.
SELF_CONTAINED = (
    '[project]\nname = "x"\nversion = "0.0.0"\nrequires-python = ">=3.10"\n'
)


def _git_init_commit(tmp_path: Path, content: dict[str, str]) -> None:
    """Create a tiny git repo with one commit so git archive works."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@agentops"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True
    )
    for name, text in content.items():
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
    )


# ---------------------------------------------------------------------------
# Unit test: extract_permitted
# ---------------------------------------------------------------------------

@pytest.mark.docker
def test_extract_permitted_blocks_sensitive_and_copies_allowed(tmp_path: Path):
    """Container writes NOTES.md (allowed) and secrets.py (denied via is_sensitive_path).

    After extract_permitted:
    - NOTES.md is present on the host.
    - secrets.py is NOT on the host.
    - Returns extracted=["NOTES.md"], blocked=["secrets.py"].
    """
    _git_init_commit(tmp_path, {"pyproject.toml": SELF_CONTAINED})

    ws = DockerWorkspace(
        tmp_path,
        isolation="full",
        # Skip sync and smoke for speed — we just need the baseline git commit.
        sync_cmd=("true",),
        smoke_cmd=("true",),
    )
    try:
        result = ws.prepare()
        assert result.ok, f"prepare failed: {result.diagnostic}"

        # Worker writes two files inside the container.
        ws.run(
            ["sh", "-c", "echo allowed > /workspace/NOTES.md && echo leak > /workspace/secrets.py"],
            timeout_seconds=30,
        )

        extracted, blocked = ws.extract_permitted(is_sensitive_path)
    finally:
        ws.cleanup()

    assert extracted == ["NOTES.md"], f"extracted: {extracted}"
    assert blocked == ["secrets.py"], f"blocked: {blocked}"

    assert (tmp_path / "NOTES.md").exists(), "NOTES.md should have been copied to host"
    assert not (tmp_path / "secrets.py").exists(), "secrets.py must NOT exist on host"


# ---------------------------------------------------------------------------
# Full-run integration test via run_harness
# ---------------------------------------------------------------------------

@pytest.mark.docker
def test_full_sandbox_run_blocks_secrets_py(tmp_path: Path):
    """Full run_harness with worker_command writing NOTES.md + secrets.py.

    Expectations:
    - secrets.py is NOT on the host after the run.
    - record.sandbox_blocked == ["secrets.py"].
    - NOTES.md IS on the host.
    - record.status == "completed" (worker exited 0).
    """
    from app.core.graph import run_harness

    _git_init_commit(tmp_path, {"pyproject.toml": SELF_CONTAINED})

    storage = tmp_path / "runs.jsonl"
    record = run_harness(
        repo_path=tmp_path,
        task="sandbox test",
        storage_path=storage,
        worker_command="sh -c 'echo a>NOTES.md; echo leak>secrets.py'",
        worker_timeout_seconds=60,
        workspace_kind="docker",
        isolation="full",
        # Skip expensive test commands inside the container.
        test_commands=["true"],
    )

    assert not (tmp_path / "secrets.py").exists(), (
        "secrets.py must NOT be present on the host after sandbox run"
    )
    assert record.sandbox_blocked == ["secrets.py"], (
        f"Expected sandbox_blocked==['secrets.py'], got {record.sandbox_blocked}"
    )
    assert (tmp_path / "NOTES.md").exists(), "NOTES.md should have been extracted to host"
