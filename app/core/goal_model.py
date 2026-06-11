from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.schemas.goal_model import ProductGoalModel

GOAL_MODEL_FILENAME = "agentops.goals.yaml"


class GoalModelError(ValueError):
    """Raised when an intent graph file exists but cannot be parsed/validated."""


def load_goal_model(repo_path: Path) -> ProductGoalModel | None:
    path = repo_path / GOAL_MODEL_FILENAME
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GoalModelError(f"Invalid YAML in {path}: {exc}") from exc
    try:
        return ProductGoalModel.model_validate(raw)
    except ValidationError as exc:
        raise GoalModelError(f"Invalid goal model in {path}: {exc}") from exc
