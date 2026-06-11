import pytest
from pydantic import ValidationError

from app.schemas.goal_model import Goal, ProductGoalModel


def sample_model() -> ProductGoalModel:
    return ProductGoalModel(
        north_star="A local control harness for coding agents.",
        not_this=["A hosted SaaS that holds your code."],
        constraints=["Local-first", "No OpenAI SDK"],
        goals=[
            Goal(
                id="G1",
                statement="Ground every worker in deterministic repo structure.",
                rationale="Cuts blind exploration.",
                priority="now",
                success_when=[
                    "repo graph built without an LLM call",
                    "worker packet includes impacted subgraph",
                ],
                scope_out=["model fine-tuning"],
            )
        ],
    )


def test_goal_lookup_returns_goal_by_id():
    model = sample_model()
    assert model.goal("G1").statement.startswith("Ground every worker")
    assert model.goal("G404") is None


def test_invalid_priority_is_rejected():
    with pytest.raises(ValidationError):
        Goal(
            id="G2",
            statement="x",
            rationale="y",
            priority="someday",  # not in now|next|later
            success_when=["z"],
            scope_out=[],
        )
