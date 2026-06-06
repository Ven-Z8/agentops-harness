from app.core.llm import LLMClient
from app.prompts.planner import build_planner_prompt
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.repo import RepoProfile


class Planner:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    def create_plan(
        self,
        task: str,
        repo_profile: RepoProfile,
        memory_lessons: list[str] | None = None,
    ) -> ImplementationPlan:
        lessons = memory_lessons or []
        if self.llm_client is not None:
            return self.llm_client.generate_structured(
                self._build_prompt(task, repo_profile, lessons),
                ImplementationPlan,
            )

        likely_app_files = repo_profile.entrypoints or repo_profile.source_files[:3]
        likely_test_files = [
            path for path in repo_profile.source_files if path.startswith("tests/")
        ] or ["tests/test_health.py"]

        framework = self._display_framework(repo_profile.framework or repo_profile.language)

        return ImplementationPlan(
            task=task,
            summary=f"Implement '{task}' in the detected {framework} project.",
            steps=[
                PlanStep(
                    id=1,
                    title="Inspect application entrypoints",
                    description=(
                        "Review the runtime entrypoints and understand where the behavior belongs."
                    ),
                    files_to_inspect=likely_app_files,
                ),
                PlanStep(
                    id=2,
                    title="Add focused implementation",
                    description="Make the smallest controlled code change that satisfies the task.",
                    files_to_inspect=likely_app_files,
                    files_to_edit=likely_app_files,
                ),
                PlanStep(
                    id=3,
                    title="Add or update tests",
                    description=(
                        "Cover the new behavior with a focused test before expanding scope."
                    ),
                    files_to_inspect=likely_test_files,
                    files_to_edit=likely_test_files,
                    tests=["python -m pytest -q"],
                ),
            ],
            acceptance_criteria=[
                "The requested behavior is implemented in the appropriate application layer.",
                "Relevant tests pass locally.",
                "The diff stays focused and avoids unrelated refactors.",
            ],
            tests_to_run=["python -m pytest -q", "ruff check ."],
            risk_notes=[
                *(f"Past experience: {lesson}" for lesson in lessons),
                "Require approval before editing secrets, auth, payment, or dependency files.",
                "Block destructive shell commands and direct force-push style operations.",
            ],
        )

    def _build_prompt(
        self,
        task: str,
        repo_profile: RepoProfile,
        lessons: list[str] | None = None,
    ) -> str:
        return build_planner_prompt(
            task=task,
            repo_profile=repo_profile,
            memory_lessons=lessons,
        )

    def _display_framework(self, framework: str | None) -> str:
        if not framework:
            return "Unknown"
        if framework.lower() == "fastapi":
            return "FastAPI"
        return framework
