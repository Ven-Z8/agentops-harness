from __future__ import annotations

from app.core.repo_graph import RepoGraph, RepoGraphQuery
from app.schemas.repo import RepoProfile


def build_planner_prompt(
    *,
    task: str,
    repo_profile: RepoProfile,
    repo_graph: RepoGraph | None = None,
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
    graph_block = _graph_section(repo_graph)

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
{graph_block}
Lessons recalled from similar past runs (experiential memory, §3.2.3):
{lessons_block}

Planning rules:
- Keep the plan small and implementation-oriented.
- Include likely files to inspect and edit.
- Include acceptance criteria.
- Include exact validation commands. Prefer the recommended validation commands above.
- Mention risk notes for secrets, auth, dependency, and broad refactor hazards.
"""


def _graph_section(repo_graph: RepoGraph | None) -> str:
    if repo_graph is None:
        return ""
    context = RepoGraphQuery(repo_graph).planner_context()
    lines = [
        "",
        "Repository graph (deterministic scan, structure-grounded planning):",
        f"- Languages: {_inline(context.languages)}",
        f"- Frameworks: {_inline(context.frameworks)}",
        f"- Build tools: {_inline(context.build_tools)}",
        f"- Test frameworks: {_inline(context.test_frameworks)}",
        f"- Entrypoint candidates: {_inline(context.entrypoint_candidates)}",
        f"- Routes: {_inline(context.routes)}",
        f"- Route files: {_inline(context.route_files)}",
        f"- Likely test files: {_inline(context.test_files)}",
        f"- Dependencies: {_inline(context.dependencies)}",
        f"- Risks: {_inline(context.risks)}",
        f"- Recommended validation commands: {_inline(context.validation_commands)}",
        "",
    ]
    return "\n".join(lines)


def _inline(items: list[str], limit: int = 20) -> str:
    if not items:
        return "none detected"
    shown = items[:limit]
    suffix = ", …" if len(items) > limit else ""
    return ", ".join(shown) + suffix


def _display_framework(framework: str | None) -> str:
    if not framework:
        return "Unknown"
    if framework.lower() == "fastapi":
        return "FastAPI"
    return framework
