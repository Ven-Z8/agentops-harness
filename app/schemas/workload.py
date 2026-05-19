from pydantic import BaseModel, Field


class WorkloadExpected(BaseModel):
    """Gates enforced when evaluating a workload manifest against a completed run."""

    max_risk_score: int | None = None
    required_commands: list[str] = Field(
        default_factory=list,
        description=(
            "Each string must match a command executed in the harness test step (exact)."
        ),
    )


class WorkloadManifest(BaseModel):
    name: str
    repo: str
    task: str
    expected: WorkloadExpected = Field(default_factory=WorkloadExpected)


class WorkloadGateResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
