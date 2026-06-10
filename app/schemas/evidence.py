from typing import Literal

from pydantic import BaseModel, Field

EvidenceSeverity = Literal["info", "warning", "error"]


class EvidenceFinding(BaseModel):
    severity: EvidenceSeverity
    claim: str
    reason: str
    evidence: str
    claim_type: str = "unsupported_claim"
    source_of_truth: str = "run_record"
    expected: str = ""
    observed: str = ""
    citation: str = ""


class EvidenceReport(BaseModel):
    grounded: bool = True
    unsupported_claim_count: int = 0
    findings: list[EvidenceFinding] = Field(default_factory=list)
