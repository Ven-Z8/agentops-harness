"""Capability packs — the outer loop equips the inner loop per repo/task.

`loader` reads a pack from disk and assembles its injectable parts (skills →
system-prompt suffix, tools → allowlisted name list, hooks → callbacks).
`selector` chooses a pack from an explicit `--pack` value (auto-selection by
repo profile is a future hook). The loader is deterministic and SDK-free so it
can be unit-tested without OpenHands installed.
"""

from app.core.packs.loader import (
    ALLOWED_TOOL_NAMES,
    PackError,
    assemble_agent_inputs,
    discover_pack,
    load_hook_callables,
    load_pack,
    pack_system_suffix,
    resolve_tool_names,
)
from app.core.packs.selector import select_pack

__all__ = [
    "ALLOWED_TOOL_NAMES",
    "PackError",
    "assemble_agent_inputs",
    "discover_pack",
    "load_hook_callables",
    "load_pack",
    "pack_system_suffix",
    "resolve_tool_names",
    "select_pack",
]
