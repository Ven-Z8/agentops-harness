from typing import Literal

from pydantic import BaseModel, Field

QualitySeverity = Literal["warning", "error"]


class ReportQualityFinding(BaseModel):
    severity: QualitySeverity
    reason: str
    evidence: str


class ReportQualityReport(BaseModel):
    passed: bool = True
    fallback_used: bool = False
    findings: list[ReportQualityFinding] = Field(default_factory=list)

