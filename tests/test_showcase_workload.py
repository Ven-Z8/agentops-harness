import os
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path("examples/showcase/fixtures/pydantic-v1-app")


def test_legacy_fixture_contains_real_v1_migration_seams() -> None:
    models = (FIXTURE / "app" / "models.py").read_text(encoding="utf-8")
    service = (FIXTURE / "app" / "service.py").read_text(encoding="utf-8")

    assert "@validator" in models
    assert "class Config:" in models
    assert "orm_mode" in models
    assert ".dict(" in service
    assert ".from_orm(" in service


def test_fixture_lock_keeps_canonical_uv_test_run_clean(tmp_path: Path) -> None:
    lockfile = FIXTURE / "uv.lock"
    assert lockfile.is_file()
    assert "pydantic-v1-migration-fixture" in lockfile.read_text(encoding="utf-8")

    repo = tmp_path / "fixture"
    shutil.copytree(FIXTURE, repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AgentOps Showcase",
            "-c",
            "user.email=showcase@agentops.local",
            "commit",
            "-qm",
            "fixture baseline",
        ],
        cwd=repo,
        check=True,
    )

    isolated_env = os.environ.copy()
    isolated_env.pop("VIRTUAL_ENV", None)
    harness_bin = str(Path(sys.executable).parent)
    isolated_env["PATH"] = os.pathsep.join(
        entry for entry in isolated_env["PATH"].split(os.pathsep) if entry != harness_bin
    )
    subprocess.run(
        ["uv", "run", "pytest", "-q"], cwd=repo, env=isolated_env, check=True
    )
    subprocess.run(
        ["uv", "run", "ruff", "check", "."], cwd=repo, env=isolated_env, check=True
    )

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
