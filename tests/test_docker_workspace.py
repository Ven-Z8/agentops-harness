"""DockerWorkspace tests — bounded and auto-skipped when Docker is unavailable.

Every docker call inside DockerWorkspace is timeout-bounded, so these tests cannot
hang the suite; a missing/slow daemon skips or fails fast rather than blocking.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.workspace.docker import DockerWorkspace


def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_up(), reason="docker daemon not available")

SELF_CONTAINED = '[project]\nname = "x"\nversion = "0.0.0"\nrequires-python = ">=3.10"\n'
BROKEN_DEP = (
    '[project]\nname = "x"\nversion = "0.0.0"\nrequires-python = ">=3.10"\n'
    'dependencies = ["nonexistent-zzz-agentops-pkg==9.9.9"]\n'
)


def test_prepare_ok_for_self_contained_repo(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(SELF_CONTAINED)
    ws = DockerWorkspace(tmp_path)
    try:
        result = ws.prepare()
        assert result.ok is True, result.diagnostic
    finally:
        ws.cleanup()


def test_prepare_fails_fast_on_broken_dep(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(BROKEN_DEP)
    ws = DockerWorkspace(tmp_path)
    try:
        result = ws.prepare()
        assert result.ok is False
        assert result.diagnostic
    finally:
        ws.cleanup()


def test_run_executes_inside_container(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(SELF_CONTAINED)
    ws = DockerWorkspace(tmp_path)
    try:
        assert ws.prepare().ok
        result = ws.run(["python", "-c", "print('hi-from-container')"], timeout_seconds=30)
        assert result.exit_code == 0
        assert "hi-from-container" in result.stdout
    finally:
        ws.cleanup()
