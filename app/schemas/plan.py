from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: int
    title: str
    description: str
    files_to_inspect: list[str] = Field(default_factory=list)
    files_to_edit: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    task: str
    summary: str
    steps: list[PlanStep] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)

