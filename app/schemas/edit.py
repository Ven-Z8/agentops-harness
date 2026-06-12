from typing import Literal

from pydantic import BaseModel, Field

EditMode = Literal["observe", "external_worker"]
ExternalEditStatus = Literal[
    "completed",
    "failed",
    "blocked",
    "timeout",
    "setup_missing",
    "auth_missing",
]


class ExternalEditResult(BaseModel):
    mode: EditMode = "external_worker"
    status: ExternalEditStatus
    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    termination_reason: str | None = None
    worker_type: str | None = None
    artifact_paths: dict[str, str | None] = Field(default_factory=dict)
