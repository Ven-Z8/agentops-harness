"""Load a capability pack and assemble its injectable parts.

Deterministic and free of the OpenHands SDK so it unit-tests without it. The
runner calls `assemble_agent_inputs()` to turn a pack into the exact things it
feeds the inner agent: a system-prompt suffix (skills), a tool-name list
(allowlisted), and hook callables (callbacks).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.schemas.pack import CapabilityPack, PackManifest, PackSkill

MANIFEST_FILENAME = "manifest.yaml"
HOOKS_FILENAME = "hooks.py"
SKILLS_DIRNAME = "skills"

# Terminal/file-only guardrail: a pack may enable only these built-in tools — no
# browser, no network. Mirrors openhands_config.OPENHANDS_TOOL_NAMES.
ALLOWED_TOOL_NAMES = frozenset(
    {"terminal", "file_editor", "task_tracker", "grep", "glob", "task_tool_set"}
)

# Built-in packs shipped with the harness: <repo_root>/packs/.
BUILTIN_PACKS_ROOT = Path(__file__).resolve().parents[3] / "packs"


class PackError(Exception):
    """A pack could not be located, parsed, or violates a guardrail."""


def discover_pack(name_or_path: str, search_root: Path | None = None) -> Path:
    """Resolve a `--pack` value (a path, or a name under a packs root) to a dir."""
    candidate = Path(name_or_path)
    if (candidate / MANIFEST_FILENAME).is_file():
        return candidate
    for root in (search_root, BUILTIN_PACKS_ROOT):
        if root is None:
            continue
        resolved = root / name_or_path
        if (resolved / MANIFEST_FILENAME).is_file():
            return resolved
    raise PackError(f"Capability pack not found: {name_or_path!r}")


def load_pack(pack_dir: Path) -> CapabilityPack:
    """Parse a pack directory into a CapabilityPack, enforcing the tool guardrail."""
    pack_dir = Path(pack_dir)
    manifest_path = pack_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PackError(f"Pack manifest not found: {manifest_path}")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest = PackManifest.model_validate(raw)
    except (ValidationError, yaml.YAMLError) as exc:
        raise PackError(f"Invalid pack manifest {manifest_path}: {exc}") from exc

    _enforce_tool_allowlist(manifest.tools)

    skills: list[PackSkill] = []
    for relative in manifest.skills:
        skill_path = pack_dir / SKILLS_DIRNAME / relative
        if not skill_path.is_file():
            raise PackError(f"Pack skill not found: {skill_path}")
        skills.append(PackSkill(name=relative, content=skill_path.read_text(encoding="utf-8")))

    return CapabilityPack(manifest=manifest, root=str(pack_dir), skills=skills)


def pack_system_suffix(pack: CapabilityPack) -> str:
    """The pack's skills, concatenated into a system-prompt suffix."""
    if not pack.skills:
        return ""
    header = f"# Capability pack: {pack.manifest.name} ({pack.manifest.domain})"
    parts = [header, pack.manifest.description.strip()]
    for skill in pack.skills:
        parts.append(f"\n## Skill — {skill.name}\n\n{skill.content.strip()}")
    return "\n".join(part for part in parts if part).strip()


def resolve_tool_names(pack: CapabilityPack, default: list[str]) -> list[str]:
    """Tool names the agent should expose: the pack's subset, or the default set.

    A pack tool that passes the guardrail but is not in the runner's ``default``
    set (typo, or a tool this runner does not expose) is a misconfiguration — it
    raises rather than being silently dropped, so the pack author can diagnose it.
    """
    if not pack.manifest.tools:
        return list(default)
    _enforce_tool_allowlist(pack.manifest.tools)
    available = set(default)
    unavailable = [name for name in pack.manifest.tools if name not in available]
    if unavailable:
        raise PackError(
            f"Pack tools not available in the runner's tool set: {unavailable}. "
            f"Available: {sorted(available)}."
        )
    return list(pack.manifest.tools)


def load_hook_callables(pack: CapabilityPack) -> list[Callable]:
    """Import the pack's hooks.py and return the manifest-listed callables."""
    if not pack.manifest.hooks:
        return []
    hooks_path = Path(pack.root) / HOOKS_FILENAME
    if not hooks_path.is_file():
        raise PackError(f"Pack lists hooks but {hooks_path} is missing")
    spec = importlib.util.spec_from_file_location(
        f"agentops_pack_{pack.manifest.name}_hooks", hooks_path
    )
    if spec is None or spec.loader is None:
        raise PackError(f"Could not load pack hooks: {hooks_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    callables: list[Callable] = []
    for name in pack.manifest.hooks:
        hook = getattr(module, name, None)
        if not callable(hook):
            raise PackError(f"Pack hook {name!r} is not a callable in {hooks_path}")
        callables.append(hook)
    return callables


def assemble_agent_inputs(
    pack: CapabilityPack | None,
    *,
    base_system_suffix: str,
    default_tools: list[str],
) -> tuple[str, list[str], list[Callable]]:
    """Fold a pack into the concrete inputs the inner agent receives.

    Returns ``(system_suffix, tool_names, hook_callables)``. With no pack, this is
    the harness baseline unchanged — so the caller has one code path either way.
    """
    if pack is None:
        return base_system_suffix, list(default_tools), []
    pack_suffix = pack_system_suffix(pack)
    system_suffix = (
        f"{base_system_suffix}\n\n{pack_suffix}".strip() if pack_suffix else base_system_suffix
    )
    tool_names = resolve_tool_names(pack, default_tools)
    return system_suffix, tool_names, load_hook_callables(pack)


def _enforce_tool_allowlist(tools: list[str]) -> None:
    forbidden = [name for name in tools if name not in ALLOWED_TOOL_NAMES]
    if forbidden:
        raise PackError(
            "Pack tools must be terminal/file-only (no browser/network). "
            f"Disallowed: {forbidden}. Allowed: {sorted(ALLOWED_TOOL_NAMES)}."
        )
