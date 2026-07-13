from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.pack import CapabilityPackProvenance


class WorkerLoopSummary(BaseModel):
    worker_type: str = "openhands"
    loop_owner: str = "openhands_sdk"
    agentops_role: str = "outer_governor"
    model: str | None = None
    status: str
    exit_code: int | None = None
    duration_seconds: float | None = None
    tools_requested: list[str] = Field(default_factory=list)
    prompt_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    event_log_path: str | None = None
    observable_event_count: int = 0
    termination_reason: str | None = None
    setup_error: str | None = None
    notes: list[str] = Field(default_factory=list)
    capability_pack: CapabilityPackProvenance | None = None


class WorkerArtifactPaths(BaseModel):
    prompt: str
    stdout: str
    stderr: str
    summary: str
    result: str
    events: str | None = None
    scorecard: str | None = None


class WorkerScorecard(BaseModel):
    worker_type: str = "openhands"
    task_id: str | None = None
    status: str
    duration_seconds: float | None = None
    changed_file_count: int | None = None
    tests_attempted_by_worker: bool | None = None
    agentops_tests_passed: bool | None = None
    permission_violations: int | None = None
    unsupported_claims: int | None = None
    risk_level: str | None = None
    convergence_type: str | None = None
    notes: list[str] = Field(default_factory=list)
