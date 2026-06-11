from __future__ import annotations

from pydantic import BaseModel, Field


class PreDispatchDecision(BaseModel):
    blocked: bool = False
    denied_paths: list[str] = Field(default_factory=list)
    reason: str = ""
