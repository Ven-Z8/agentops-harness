from pathlib import Path

from app.core.graph import run_harness

GOALS = """\
north_star: Local control harness.
goals:
  - id: G1
    statement: Ground worker runs.
    priority: now
    success_when:
      - healthz endpoint added
    scope_out: []
"""


def test_run_harness_attaches_product_review_and_section(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo).mkdir()
    (repo / "agentops.goals.yaml").write_text(GOALS)
    (repo / "main.py").write_text("def f():\n    return 1\n")

    record = run_harness(
        repo_path=repo, task="Add healthz endpoint",
        storage_path=tmp_path / "runs.db", target_goal_id="G1",
    )

    assert record.product_review.overall_verdict != "not_evaluated"
    assert "## Product Review" in record.final_report.markdown


def test_run_harness_without_goal_file_is_not_evaluated(tmp_path: Path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "main.py").write_text("def f():\n    return 1\n")
    record = run_harness(repo_path=repo, task="x", storage_path=tmp_path / "runs.db")
    assert record.product_review.overall_verdict == "not_evaluated"


class _RaisingLLM:
    """An LLM client whose product-review structured call always fails."""

    def generate_structured(self, prompt: str, schema: type) -> object:
        raise RuntimeError("provider unavailable")

    def generate_text(self, prompt: str) -> str:
        raise RuntimeError("provider unavailable")


def test_product_review_llm_failure_logs_provider_fallback(tmp_path: Path):
    repo = tmp_path / "repo3"
    repo.mkdir()
    (repo / "agentops.goals.yaml").write_text(GOALS)
    (repo / "main.py").write_text("def f():\n    return 1\n")

    record = run_harness(
        repo_path=repo, task="Add healthz endpoint",
        storage_path=tmp_path / "runs.db", target_goal_id="G1",
        llm_client=_RaisingLLM(),
    )

    # The run still completes with a valid deterministic review, and the fallback
    # is recorded (not silently swallowed).
    assert record.product_review.overall_verdict != "not_evaluated"
    assert "provider_fallback:build_product_review" in record.execution_logs
