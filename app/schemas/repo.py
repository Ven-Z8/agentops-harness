from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RepoProfile(BaseModel):
    repo_path: str
    language: str | None = None
    framework: str | None = None
    package_manager: str | None = None
    test_framework: str | None = None
    entrypoints: list[str] = Field(default_factory=list)
    important_folders: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

