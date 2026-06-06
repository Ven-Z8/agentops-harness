from pathlib import Path

from app.agents.planner import Planner
from app.agents.pr_writer import PRWriter
from app.agents.reviewer import Reviewer
from app.core.graph import run_harness
from app.core.repo_graph import RepoGraphBuilder
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewFinding, ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.test import CommandResult, TestRunSummary


class FakeLLMClient:
    def __init__(self) -> None:
        self.structured_prompts: list[str] = []
        self.text_prompts: list[str] = []

    def generate_text(self, prompt: str) -> str:
        self.text_prompts.append(prompt)
        return """# LLM PR Report

## Summary
LLM-written report.

## What changed
No files changed.

## Files changed
- No files changed

## Tests run
- `python -m pytest -q`: exit 0

## Risk assessment
- Score: 12/100

## Reviewer notes
- Review completed.

## Follow-up tasks
- Apply the implementation plan.
"""

    def generate_structured(self, prompt: str, schema: type) -> object:
        self.structured_prompts.append(prompt)
        if schema is ImplementationPlan:
            return ImplementationPlan(
                task="Add request logging middleware",
                summary="LLM plan for request logging middleware.",
                steps=[
                    PlanStep(
                        id=1,
                        title="Add middleware",
                        description="Install request logging middleware in the FastAPI app.",
                        files_to_inspect=["app/main.py"],
                        files_to_edit=["app/main.py"],
                        tests=["python -m pytest -q"],
                    )
                ],
                acceptance_criteria=["Requests are logged with method, path, and status code."],
                tests_to_run=["python -m pytest -q"],
                risk_notes=["Middleware can affect every request."],
            )
        if schema is ReviewReport:
            return ReviewReport(
                summary="LLM review completed.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        title="Middleware scope",
                        description="Request logging middleware affects every route.",
                        file_path="app/main.py",
                        recommendation="Verify request and response logging in tests.",
                    )
                ],
            )
        raise AssertionError(f"Unexpected schema: {schema}")


def test_planner_uses_llm_client_when_provided() -> None:
    llm_client = FakeLLMClient()
    profile = RepoProfile(
        repo_path="/repo",
        language="python",
        framework="fastapi",
        entrypoints=["app/main.py"],
        source_files=["app/main.py", "tests/test_health.py"],
    )

    plan = Planner(llm_client=llm_client).create_plan("Add request logging middleware", profile)

    assert plan.summary == "LLM plan for request logging middleware."
    assert llm_client.structured_prompts
    assert "FastAPI" in llm_client.structured_prompts[0]


def test_planner_prompt_includes_graph_context_for_llm() -> None:
    llm_client = FakeLLMClient()
    graph = RepoGraphBuilder().build(Path("examples/sample_fastapi_app"))
    profile = RepoProfile(
        repo_path="examples/sample_fastapi_app",
        language="python",
        framework="fastapi",
        entrypoints=["app/main.py"],
        source_files=["app/main.py", "tests/test_health.py"],
    )

    Planner(llm_client=llm_client).create_plan("Add a route", profile, repo_graph=graph)

    prompt = llm_client.structured_prompts[0]
    assert "Repository graph" in prompt
    assert "GET /health" in prompt
    assert "app/main.py" in prompt
    assert "uv run pytest -q" in prompt


def test_reviewer_uses_llm_client_when_provided() -> None:
    llm_client = FakeLLMClient()
    test_results = TestRunSummary(
        commands=[
            CommandResult(
                command="python -m pytest -q",
                exit_code=0,
                duration_seconds=0.1,
                stdout="1 passed",
                stderr="",
            )
        ]
    )

    report = Reviewer(llm_client=llm_client).review(["app/main.py"], test_results)

    assert report.summary == "LLM review completed."
    assert report.findings[0].title == "Middleware scope"
    assert "app/main.py" in llm_client.structured_prompts[0]


def test_pr_writer_uses_llm_client_when_provided() -> None:
    llm_client = FakeLLMClient()
    final_report = PRWriter(llm_client=llm_client).write(
        task="Add request logging middleware",
        plan=ImplementationPlan(
            task="Add request logging middleware",
            summary="Add middleware.",
            acceptance_criteria=["Requests are logged."],
        ),
        changed_files=["app/main.py"],
        test_results=TestRunSummary(
            commands=[
                CommandResult(
                    command="python -m pytest -q",
                    exit_code=0,
                    duration_seconds=0.1,
                    stdout="1 passed",
                    stderr="",
                )
            ]
        ),
        review_report=ReviewReport(summary="Clean.", findings=[]),
        risk_report=RiskReport(risk_score=12, risk_level="low", factors=["Small change"]),
    )

    assert final_report == FinalReport(
        title="AgentOps Harness Report",
        markdown="""# LLM PR Report

## Summary
LLM-written report.

## What changed
No files changed.

## Files changed
- No files changed

## Tests run
- `python -m pytest -q`: exit 0

## Risk assessment
- Score: 12/100

## Reviewer notes
- Review completed.

## Follow-up tasks
- Apply the implementation plan.
""",
    )
    assert "Add request logging middleware" in llm_client.text_prompts[0]


def test_run_harness_routes_llm_client_through_graph(tmp_path: Path) -> None:
    llm_client = FakeLLMClient()

    record = run_harness(
        repo_path=Path("examples/sample_fastapi_app"),
        task="Add request logging middleware",
        storage_path=tmp_path / "runs.db",
        llm_client=llm_client,
    )

    assert record.plan.summary == "LLM plan for request logging middleware."
    assert record.review_report.summary == "LLM review completed."
    assert record.final_report.markdown.startswith("# LLM PR Report")
