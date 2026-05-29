import subprocess
from pathlib import Path

from app.core.graph import run_harness

_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".venv"}


def _copy_sample_repo(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _SKIP_PARTS.intersection(relative.parts):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True
    )


def test_run_harness_produces_report_and_persists_record(tmp_path: Path) -> None:
    # Run against an isolated clean git copy of the fixture so the fixture does
    # not need to be a nested git repo (which cannot be cloned from origin).
    repo = tmp_path / "sample_fastapi_app"
    _copy_sample_repo(Path("examples/sample_fastapi_app"), repo)
    _init_git_repo(repo)
    storage_path = tmp_path / "runs.jsonl"

    result = run_harness(
        repo_path=repo,
        task="Add request logging middleware",
        storage_path=storage_path,
        test_commands=["python -m pytest -q"],
    )

    assert result.status == "completed"
    assert result.repo_profile.framework == "fastapi"
    assert result.plan.acceptance_criteria
    assert result.changed_files == []
    assert result.test_results.passed is True
    assert "Risk assessment" in result.final_report.markdown
    assert storage_path.exists()
    assert result.run_id in storage_path.read_text()
