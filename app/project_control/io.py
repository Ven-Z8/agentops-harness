from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypeVar

import yaml
from pydantic import BaseModel

from app.project_control.errors import InvalidControlRoom

T = TypeVar("T", bound=BaseModel)


def resolve_inside(path: Path, root: Path) -> Path:
    """Resolve a non-symlink path only when it remains inside *root*."""
    root_resolved = root.resolve(strict=True)
    candidate = path if path.is_absolute() else root_resolved / path
    try:
        relative = candidate.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError(f"Path must remain inside repository: {path}") from error
    if ".." in relative.parts or path.is_symlink():
        raise ValueError(f"Path must resolve inside repository without symlink: {path}")

    current = root_resolved
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Path must resolve inside repository without symlink: {path}")

    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"Path must remain inside repository: {path}")
    return resolved


def load_yaml(path: Path, model_type: type[T], *, root: Path) -> T:
    resolved = resolve_inside(path, root)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return model_type.model_validate(payload)


def load_frontmatter(path: Path, model_type: type[T], *, root: Path) -> T:
    resolved = resolve_inside(path, root)
    lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise InvalidControlRoom(f"Invalid frontmatter in {path}: missing opening delimiter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        raise InvalidControlRoom(f"Invalid frontmatter in {path}: missing closing delimiter")
    payload = yaml.safe_load("".join(lines[1:closing_index]))
    if not isinstance(payload, dict) or not payload:
        raise InvalidControlRoom(f"Invalid frontmatter in {path}: expected non-empty mapping")
    return model_type.model_validate(payload)


def atomic_write(path: Path, content: str, *, root: Path) -> None:
    resolved = resolve_inside(path, root)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=resolved.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(resolved)
