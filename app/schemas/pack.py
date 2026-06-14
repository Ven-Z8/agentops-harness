"""Capability pack schema (ROADMAP M3).

A capability pack is a directory the *outer* loop assembles and injects into the
inner OpenHands loop: `{ manifest.yaml, skills/*.md, hooks.py }`. The manifest
declares which skills (playbook markdown), which built-in tools (terminal/file
only), and which hook callables the pack contributes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PackManifest(BaseModel):
    name: str
    domain: str
    version: str = "0.1.0"
    description: str = ""
    # Markdown filenames under the pack's skills/ directory.
    skills: list[str] = Field(default_factory=list)
    # Built-in tool names to enable for this pack (subset of the terminal/file-only
    # allowlist). Empty means "use the harness default tool set".
    tools: list[str] = Field(default_factory=list)
    # Callable names exported by the pack's hooks.py, appended as loop callbacks.
    hooks: list[str] = Field(default_factory=list)

    @field_validator("skills", "tools", "hooks", mode="before")
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        # An empty `tools:` / `hooks:` key in YAML parses to None — treat as [].
        return value or []


class PackSkill(BaseModel):
    name: str
    content: str


class CapabilityPack(BaseModel):
    manifest: PackManifest
    root: str
    skills: list[PackSkill] = Field(default_factory=list)
