from typing import ClassVar

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    command: str
    exit_code: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""


class TestRunSummary(BaseModel):
    __test__: ClassVar[bool] = False

    commands: list[CommandResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.commands) and all(result.exit_code == 0 for result in self.commands)
