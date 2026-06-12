from __future__ import annotations

from pathlib import Path
from typing import Any


def _as_lines(values: list[str] | tuple[str, ...] | None, *, empty: str) -> str:
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {value}" for value in values)


def _model_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {}


def _format_plan(plan: Any) -> str:
    payload = _model_dict(plan)
    if not payload:
        return (
            "- No formal AgentOps plan was provided. Inspect the repo and make the "
            "smallest safe implementation that satisfies the task."
        )

    lines = []
    summary = payload.get("summary")
    if summary:
        lines.append(f"- Summary: {summary}")
    for step in payload.get("steps") or []:
        title = step.get("title", "Plan step")
        description = step.get("description", "")
        lines.append(f"- Step {step.get('id', '?')}: {title} - {description}".rstrip())
        files_to_inspect = step.get("files_to_inspect") or []
        files_to_edit = step.get("files_to_edit") or []
        tests = step.get("tests") or []
        if files_to_inspect:
            lines.append(f"  - Inspect: {', '.join(files_to_inspect)}")
        if files_to_edit:
            lines.append(f"  - Edit: {', '.join(files_to_edit)}")
        if tests:
            lines.append(f"  - Tests: {', '.join(tests)}")
    criteria = payload.get("acceptance_criteria") or []
    if criteria:
        lines.append("- Acceptance criteria:")
        lines.extend(f"  - {item}" for item in criteria)
    risk_notes = payload.get("risk_notes") or []
    if risk_notes:
        lines.append("- Risk notes:")
        lines.extend(f"  - {item}" for item in risk_notes)
    return "\n".join(lines) if lines else "- AgentOps provided an empty plan."


def _format_repo_context(repo_path: Path, repo_profile: Any) -> str:
    payload = _model_dict(repo_profile)
    lines = [f"- Repo path: {repo_path}"]
    for key, label in (
        ("language", "Language"),
        ("framework", "Framework"),
        ("package_manager", "Package manager"),
        ("test_framework", "Test framework"),
    ):
        if payload.get(key):
            lines.append(f"- {label}: {payload[key]}")
    for key, label in (
        ("entrypoints", "Entrypoints"),
        ("important_folders", "Important folders"),
        ("config_files", "Config files"),
    ):
        values = payload.get(key) or []
        if values:
            lines.append(f"- {label}: {', '.join(values)}")
    return "\n".join(lines)


def _plan_files(plan: Any) -> list[str]:
    payload = _model_dict(plan)
    files: list[str] = []
    for step in payload.get("steps") or []:
        files.extend(step.get("files_to_inspect") or [])
        files.extend(step.get("files_to_edit") or [])
    return sorted(set(files))


def _plan_tests(plan: Any) -> list[str]:
    payload = _model_dict(plan)
    tests = list(payload.get("tests_to_run") or [])
    for step in payload.get("steps") or []:
        tests.extend(step.get("tests") or [])
    return sorted(set(tests))


def build_worker_prompt(
    *,
    repo_path: Path,
    task: str,
    plan: Any = None,
    repo_profile: Any = None,
    files_to_edit: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    tests_to_run: list[str] | None = None,
    permission_tier: str = "standard",
) -> str:
    likely_files = files_to_edit or _plan_files(plan)
    verification_commands = tests_to_run or _plan_tests(plan)
    no_likely_files = (
        "No likely files were provided. Discover the minimal relevant files before editing."
    )
    default_forbidden_paths = (
        ".env, .env.*, **/*secret*, **/*token*, private keys, credential stores"
    )
    default_verification = (
        "Run the smallest relevant test or validation command you can identify."
    )
    return f"""\
# Worker Packet
You are a coding worker running inside AgentOps Harness.
AgentOps is the outer governance harness.
You are the inner implementation worker.

## Task
{task}

## Plan as Contract
{_format_plan(plan)}
Follow this plan unless repo inspection proves it is wrong.
If the plan is wrong, make the smallest safe correction and explain it.

## Repo Context
{_format_repo_context(repo_path, repo_profile)}

## Likely Impacted Files
{_as_lines(likely_files, empty=no_likely_files)}

## Constraints
- Keep the diff minimal.
- Do not edit unrelated files.
- Do not touch sensitive paths.
- Do not modify tests just to make them pass unless explicitly required.
- Prefer implementation changes over test weakening.
- If you cannot proceed safely, stop and explain why.

## Forbidden Actions
- Do not add secrets, credentials, tokens, private keys, or real API keys.
- Do not modify lockfiles, generated files, or CI configuration unless the plan requires it.
- Do not change public behavior outside the task scope.
- Do not claim tests passed unless you actually ran them and saw success.

## Forbidden Paths
{_as_lines(forbidden_paths, empty=default_forbidden_paths)}

## Permission Tier
{permission_tier}

## Verification Obligations
Run these if possible:
{_as_lines(verification_commands, empty=default_verification)}
If you cannot run them, explain why.

## Definition of Done
The task is done only when:
- required implementation is complete
- diff is minimal
- validation has been attempted
- no forbidden paths are touched
- final message summarizes exactly what changed

## Reporting Rules
Do not claim tests passed unless you actually ran them and saw success.
Do not claim files changed unless you changed them.
Do not claim routes/endpoints were added unless they exist in the diff.
If blocked, explain the blocker and stop.
"""
