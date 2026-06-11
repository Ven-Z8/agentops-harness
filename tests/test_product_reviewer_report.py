from app.agents.product_reviewer import ProductReviewer
from app.prompts.product_reviewer import build_product_reviewer_prompt
from app.schemas.goal_model import Goal, ProductGoalModel
from app.schemas.plan import ImplementationPlan, PlanStep
from app.schemas.product_review import ProductFinding, ProductReview
from app.schemas.report import FinalReport


def test_prompt_includes_grounding_rules():
    model = ProductGoalModel(north_star="x", goals=[Goal(id="G1", statement="s")])
    plan = ImplementationPlan(task="t", summary="s",
                              steps=[PlanStep(id=1, title="a", description="d")],
                              acceptance_criteria=["ok"], tests_to_run=["python -m pytest -q"])
    prompt = build_product_reviewer_prompt(
        task="t", plan=plan, changed_files=["app/main.py"], diff_summary="",
        goal_model=model, target_goal_id="G1",
    )
    assert "Grounding rules" in prompt
    assert "every finding must cite" in prompt.lower()
    assert "not_evaluated" in prompt


def test_append_to_report_adds_section():
    review = ProductReview(
        overall_verdict="drifted", summary="goal_alignment: fail",
        findings=[ProductFinding(lens="goal_alignment", verdict="fail",
                                 observation="touched billing", citation="agentops.goals.yaml#G1")],
    )
    report = FinalReport(title="t", markdown="# Report\n\nbody")
    out = ProductReviewer().append_to_report(report, review)
    assert "## Product Review" in out.markdown
    assert "drifted" in out.markdown
    assert "agentops.goals.yaml#G1" in out.markdown
