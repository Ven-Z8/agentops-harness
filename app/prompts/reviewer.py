from __future__ import annotations

from app.schemas.test import TestRunSummary


def build_reviewer_prompt(
    *,
    changed_files: list[str],
    test_results: TestRunSummary,
) -> str:
    files = "\n".join(f"- {path}" for path in changed_files) or "- No files changed"
    commands = "\n".join(
        (
            f"- {result.command}: exit {result.exit_code}, "
            f"{result.duration_seconds:.3f}s\n"
            f"  stdout: {result.stdout[-1000:] or '<empty>'}\n"
            f"  stderr: {result.stderr[-1000:] or '<empty>'}"
        )
        for result in test_results.commands
    )
    return f"""You are the Reviewer Agent in AgentOps Harness.

Review the changed files and validation output. Return only data matching the ReviewReport schema.

Changed files:
{files}

Validation results:
{commands or "- No validation commands were run"}

Review rules:
- Prioritize correctness, missing tests, maintainability, and security.
- Do not invent files or changes that are not listed.
- If tests failed, include a high-severity finding.
- Keep recommendations actionable and PR-review style.
"""
