from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProductLens = Literal["goal_alignment", "completeness", "value", "prioritization"]
ProductVerdict = Literal["pass", "concern", "fail", "not_evaluated"]
OverallVerdict = Literal[
    "aligned", "drifted", "overbuilt", "incomplete", "unclear", "not_evaluated"
]


class ProductFinding(BaseModel):
    lens: ProductLens
    verdict: ProductVerdict
    observation: str
    source_of_truth: str = "goal_model"
    citation: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    recommendation: str = ""


class ProductReview(BaseModel):
    overall_verdict: OverallVerdict = "not_evaluated"
    per_lens: dict[str, str] = Field(default_factory=dict)
    findings: list[ProductFinding] = Field(default_factory=list)
    summary: str = ""
    suggested_next: list[str] = Field(default_factory=list)  # STUB — deferred to v2
