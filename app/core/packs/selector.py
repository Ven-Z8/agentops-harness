"""Choose a capability pack for a run.

Explicit `--pack` (a path or a built-in pack name) wins. Auto-selection by repo
profile / task is a deliberate future hook — there are no built-in domain packs
to match against until M4 ships the migration pack — so it returns None for now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.packs.loader import discover_pack


def select_pack(
    explicit: str | None,
    *,
    repo_profile: Any = None,
    task: str | None = None,
    search_root: Path | None = None,
) -> Path | None:
    """Resolve the pack directory for a run, or None when no pack applies."""
    if explicit:
        return discover_pack(explicit, search_root)
    # Auto-selection lands with the first real domain pack (M4). Until then an
    # un-flagged run uses no pack — identical to today's behavior.
    return None
