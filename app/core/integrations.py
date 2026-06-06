from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.prompts.integrations import CURSOR_FILES, GOOSE_RECIPE


@dataclass(frozen=True)
class IntegrationInstallResult:
    created_files: list[str]


def install_cursor_pack(repo_path: Path) -> IntegrationInstallResult:
    created_files: list[str] = []
    for relative_path, content in CURSOR_FILES.items():
        target = repo_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created_files.append(relative_path)
    return IntegrationInstallResult(created_files=sorted(created_files))


def write_goose_recipe(repo_path: Path) -> Path:
    target = repo_path / ".goose/recipes/agentops-harness.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(GOOSE_RECIPE, encoding="utf-8")
    return target
