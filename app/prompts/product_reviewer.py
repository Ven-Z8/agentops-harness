from __future__ import annotations

from app.schemas.goal_model import ProductGoalModel
from app.schemas.plan import ImplementationPlan

# Cap the diff included in the prompt so a large migration diff cannot blow the context
# window. The upstream diff_body is already bounded; this is a second, prompt-local guard.
_MAX_DIFF_CHARS = 16000


def _diff_block(diff_body: str) -> str:
    body = diff_body.strip()
    if not body:
        return "Actual diff: (no diff body was captured for this run)"
    if len(body) > _MAX_DIFF_CHARS:
        body = body[:_MAX_DIFF_CHARS] + "\n... [diff truncated for prompt length]"
    return (
        "Actual diff (judge completeness against THESE concrete changes, not just the file "
        "names or the summary — e.g. confirm the work is actually finished, not merely "
        "started):\n"
        f"{body}"
    )


def build_product_reviewer_prompt(
    *, task: str, plan: ImplementationPlan, changed_files: list[str],
    diff_summary: str, goal_model: ProductGoalModel, target_goal_id: str | None,
    diff_body: str = "",
) -> str:
    goal = goal_model.goal(target_goal_id) if target_goal_id else None
    goal_block = (
        f"Target goal {goal.id}: {goal.statement}\n"
        f"  priority: {goal.priority}\n"
        f"  success_when: {goal.success_when}\n"
        f"  scope_out: {goal.scope_out}\n"
        if goal else "No specific target goal; evaluate against the whole model."
    )
    files = "\n".join(f"- {f}" for f in changed_files) or "- none"
    return f"""You are the Product Reviewer in AgentOps Harness — the CEO/CTO altitude.
You do NOT re-check code correctness (other guards do). You judge whether the work
served the product intent, across four lenses: goal_alignment, completeness, value,
prioritization.

Grounding rules (hard constraints):
- Judge ONLY against the goal model and run artifacts below.
- Every finding must cite a source_of_truth field (e.g. goal_model.G1.scope_out).
- Never invent goals, success signals, or files.
- Use verdict not_evaluated when the intent is absent rather than guessing.

Product north star: {goal_model.north_star}
Not this: {goal_model.not_this}
{goal_block}

Task: {task}
Plan summary: {plan.summary}
Changed files:
{files}
Diff summary: {diff_summary}
{_diff_block(diff_body)}
"""
