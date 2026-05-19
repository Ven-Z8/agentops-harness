from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]


class ReviewFinding(BaseModel):
    severity: Severity
    title: str
    description: str
    file_path: str | None = None
    recommendation: str


class ReviewReport(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str

