from typing import Literal

from pydantic import BaseModel

EditMode = Literal["observe", "external_worker"]
ExternalEditStatus = Literal["completed", "failed", "blocked"]


class ExternalEditResult(BaseModel):
    mode: EditMode = "external_worker"
    status: ExternalEditStatus
    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
