from app.core.llm import LLMClient
from app.core.repo_graph import RepoGraph, RepoGraphQuery
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
        repo_graph: RepoGraph | None = None,
        memory_lessons: list[str] | None = None,
    ) -> ImplementationPlan:
        lessons = memory_lessons or []
        if self.llm_client is not None:
            plan = self.llm_client.generate_structured(
                self._build_prompt(task, repo_profile, repo_graph, lessons),
                ImplementationPlan,
            )
            if repo_graph is not None:
                grounded_commands = RepoGraphQuery(repo_graph).validation_commands()
                if grounded_commands:
                    plan.tests_to_run = grounded_commands
            return plan

        if repo_graph is not None:
            return self._graph_aware_plan(task, repo_profile, repo_graph, lessons)
        return self._profile_only_plan(task, repo_profile, lessons)

    def _profile_only_plan(
        self,
        task: str,
        repo_profile: RepoProfile,
        lessons: list[str],
    ) -> ImplementationPlan:
        likely_app_files = repo_profile.entrypoints or repo_profile.source_files[:3]
        likely_test_files = [
            path for path in repo_profile.source_files if path.startswith("tests/")
        ] or ["tests/test_health.py"]
        framework = self._display_framework(repo_profile.framework or repo_profile.language)
        return self._build_plan(
            task=task,
            framework=framework,
            likely_app_files=likely_app_files,
            likely_test_files=likely_test_files,
            tests_to_run=["python -m pytest -q", "ruff check ."],
            lessons=lessons,
            extra_risk_notes=[],
        )

    def _graph_aware_plan(
        self,
        task: str,
        repo_profile: RepoProfile,
        repo_graph: RepoGraph,
        lessons: list[str],
    ) -> ImplementationPlan:
        query = RepoGraphQuery(repo_graph)

        likely_app_files = (
            query.entrypoint_candidates()
            + query.route_files()
            + query.source_files()[:3]
        )
        likely_app_files = _unique(likely_app_files) or (
            repo_profile.entrypoints or repo_profile.source_files[:3]
        )

        graph_tests = query.likely_tests_for_files(likely_app_files) + query.test_files()
        likely_test_files = _unique(graph_tests) or (
            [path for path in repo_profile.source_files if path.startswith("tests/")]
            or ["tests/test_health.py"]
        )

        tests_to_run = query.validation_commands() or ["python -m pytest -q", "ruff check ."]

        graph_framework = next(iter(repo_graph.summary.frameworks), None)
        framework = self._display_framework(
            repo_profile.framework or graph_framework or repo_profile.language
        )

        return self._build_plan(
            task=task,
            framework=framework,
            likely_app_files=likely_app_files,
            likely_test_files=likely_test_files,
            tests_to_run=tests_to_run,
            lessons=lessons,
            extra_risk_notes=query.risk_notes(),
        )

    def _build_plan(
        self,
        *,
        task: str,
        framework: str,
        likely_app_files: list[str],
        likely_test_files: list[str],
        tests_to_run: list[str],
        lessons: list[str],
        extra_risk_notes: list[str],
    ) -> ImplementationPlan:
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
                    tests=tests_to_run,
                ),
            ],
            acceptance_criteria=[
                "The requested behavior is implemented in the appropriate application layer.",
                "Relevant tests pass locally.",
                "The diff stays focused and avoids unrelated refactors.",
            ],
            tests_to_run=tests_to_run,
            risk_notes=[
                *(f"Past experience: {lesson}" for lesson in lessons),
                *extra_risk_notes,
                "Require approval before editing secrets, auth, payment, or dependency files.",
                "Block destructive shell commands and direct force-push style operations.",
            ],
        )

    def _build_prompt(
        self,
        task: str,
        repo_profile: RepoProfile,
        repo_graph: RepoGraph | None = None,
        lessons: list[str] | None = None,
    ) -> str:
        return build_planner_prompt(
            task=task,
            repo_profile=repo_profile,
            repo_graph=repo_graph,
            memory_lessons=lessons,
        )

    def _display_framework(self, framework: str | None) -> str:
        if not framework:
            return "Unknown"
        if framework.lower() == "fastapi":
            return "FastAPI"
        return framework


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
