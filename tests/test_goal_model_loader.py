from pathlib import Path

import pytest

from app.core.goal_model import GoalModelError, load_goal_model

GOALS_YAML = """\
north_star: A local control harness for coding agents.
not_this:
  - A hosted SaaS that holds your code.
constraints:
  - Local-first
goals:
  - id: G1
    statement: Ground every worker in deterministic repo structure.
    rationale: Cuts blind exploration.
    priority: now
    success_when:
      - repo graph built without an LLM call
    scope_out:
      - model fine-tuning
"""


def test_loads_goal_model_from_repo_root(tmp_path: Path):
    (tmp_path / "agentops.goals.yaml").write_text(GOALS_YAML)
    model = load_goal_model(tmp_path)
    assert model is not None
    assert model.goal("G1").priority == "now"


def test_absent_file_returns_none(tmp_path: Path):
    assert load_goal_model(tmp_path) is None


def test_malformed_file_raises_goal_model_error(tmp_path: Path):
    (tmp_path / "agentops.goals.yaml").write_text("north_star: [unterminated\n")
    with pytest.raises(GoalModelError):
        load_goal_model(tmp_path)
