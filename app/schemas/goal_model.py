from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GoalPriority = Literal["now", "next", "later"]


class Goal(BaseModel):
    id: str
    statement: str
    rationale: str = ""
    priority: GoalPriority = "now"
    success_when: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)


class ProductGoalModel(BaseModel):
    north_star: str = ""
    not_this: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)

    def goal(self, goal_id: str) -> Goal | None:
        for goal in self.goals:
            if goal.id == goal_id:
                return goal
        return None
