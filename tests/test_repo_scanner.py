from pathlib import Path

from app.agents.repo_scanner import RepoScanner


def test_scanner_profiles_sample_fastapi_app() -> None:
    repo = Path("examples/sample_fastapi_app")

    profile = RepoScanner().scan(repo)

    assert profile.language == "python"
    assert profile.framework == "fastapi"
    assert profile.package_manager == "uv"
    assert profile.test_framework == "pytest"
    assert "app/main.py" in profile.entrypoints
    assert "tests" in profile.important_folders
