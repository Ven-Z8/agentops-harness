from pathlib import Path

from app.core.graph import run_harness


class BrokenProvider:
    def generate_text(self, prompt: str) -> str:
        raise ValueError("text generation failed")

    def generate_structured(self, prompt: str, schema: type) -> object:
        raise ValueError("structured generation failed")


def test_run_harness_falls_back_when_provider_fails(tmp_path: Path) -> None:
    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware with tests",
        storage_path=tmp_path / "runs.db",
        llm_client=BrokenProvider(),
    )

    assert record.status == "completed"
    assert record.plan.summary.startswith("Implement")
    assert "Risk assessment" in record.final_report.markdown
    assert "provider_fallback:create_plan" in record.execution_logs
    assert "provider_fallback:review_diff" in record.execution_logs
    assert "provider_fallback:write_report" in record.execution_logs
