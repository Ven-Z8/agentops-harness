from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HandoffPlanStepBrief(BaseModel):
    id: int
    title: str
    description: str
    files_to_inspect: list[str] = Field(default_factory=list)
    files_to_edit: list[str] = Field(default_factory=list)


class WorkerHandoffPacket(BaseModel):
    """Portable instructions for an external worker (deterministic slice of a run)."""

    phase: Literal["completed_run", "draft_pre_worker"]
    run_id: str | None = None
    repo_path: str
    task: str
    plan_summary: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    plan_steps: list[HandoffPlanStepBrief] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    plan_risk_notes: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(
        default_factory=list,
        description="Exact commands to run after edits (prefer harness-aligned commands).",
    )
    harness_status: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    risk_score: int | None = None
    risk_level: str | None = None
    risk_blocked: bool | None = None
    edit_result_status: str | None = Field(
        default=None,
        description="Outcome of optional external worker, if configured on the run.",
    )
