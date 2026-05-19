from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "critical"]


class RiskReport(BaseModel):
    risk_score: int
    risk_level: RiskLevel
    factors: list[str] = Field(default_factory=list)
    blocked: bool = False

