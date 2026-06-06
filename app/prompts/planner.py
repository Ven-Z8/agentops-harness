from __future__ import annotations

from app.schemas.repo import RepoProfile


def build_planner_prompt(
    *,
    task: str,
    repo_profile: RepoProfile,
    memory_lessons: list[str] | None = None,
) -> str:
    framework = _display_framework(repo_profile.framework or repo_profile.language)
    source_files = "\n".join(f"- {path}" for path in repo_profile.source_files[:60])
    entrypoints = "\n".join(f"- {path}" for path in repo_profile.entrypoints)
    config_files = "\n".join(f"- {path}" for path in repo_profile.config_files)
    lessons_block = (
        "\n".join(f"- {lesson}" for lesson in memory_lessons)
        if memory_lessons
        else "- None recalled"
    )

    return f"""You are the Planner Agent in AgentOps Harness.

Create a focused, safe implementation plan for a coding agent.
Return only data matching the ImplementationPlan schema.

Task:
{task}

Repository profile:
- Language: {repo_profile.language}
- Framework: {framework}
- Package manager: {repo_profile.package_manager}
- Test framework: {repo_profile.test_framework}

Entrypoints:
{entrypoints or "- None detected"}

Config files:
{config_files or "- None detected"}

Source files:
{source_files or "- None detected"}

Lessons recalled from similar past runs (experiential memory, §3.2.3):
{lessons_block}

Planning rules:
- Keep the plan small and implementation-oriented.
- Include likely files to inspect and edit.
- Include acceptance criteria.
- Include exact validation commands.
- Mention risk notes for secrets, auth, dependency, and broad refactor hazards.
"""


def _display_framework(framework: str | None) -> str:
    if not framework:
        return "Unknown"
    if framework.lower() == "fastapi":
        return "FastAPI"
    return framework
