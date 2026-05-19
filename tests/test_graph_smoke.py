from pathlib import Path

from app.core.graph import run_harness


def test_run_harness_produces_report_and_persists_record(tmp_path: Path) -> None:
    repo = Path("examples/sample_fastapi_app")
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
