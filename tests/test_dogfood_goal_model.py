from pathlib import Path

from app.core.goal_model import load_goal_model


def test_repo_ships_a_valid_goal_model():
    model = load_goal_model(Path("."))
    assert model is not None, "agentops.goals.yaml must exist at repo root"
    assert model.north_star
    assert len(model.goals) >= 1
    for goal in model.goals:
        assert goal.success_when, f"{goal.id} must list discrete success_when signals"
