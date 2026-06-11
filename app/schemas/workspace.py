from __future__ import annotations

from pydantic import BaseModel


class PrepareResult(BaseModel):
    ok: bool = True
    diagnostic: str = ""
    smoke_command: str = ""
    smoke_exit_code: int | None = None
