from __future__ import annotations

from app.schemas.goal_model import ProductGoalModel
from app.schemas.plan import ImplementationPlan


def build_product_reviewer_prompt(
    *, task: str, plan: ImplementationPlan, changed_files: list[str],
    diff_summary: str, goal_model: ProductGoalModel, target_goal_id: str | None,
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
"""
