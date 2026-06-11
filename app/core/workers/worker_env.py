"""Locate worker CLIs and build their subprocess env robustly.

GUI-launched (e.g. the desktop app) or detached harness processes often run with a
stripped PATH that misses the npm / bun / homebrew / cargo global-bin dirs where
worker CLIs (codex, claude, opencode) actually live. `shutil.which("codex")` then
returns None and the harness wrongly reports the worker as "not installed". These
helpers add the common global-bin locations so workers are found regardless of how
the harness was launched.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_GLOBAL_BIN_DIRS = [
    Path.home() / ".npm-global" / "bin",
    Path.home() / ".bun" / "bin",
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path.home() / ".cargo" / "bin",
]


def worker_env() -> dict[str, str]:
    """Return os.environ plus common global-bin dirs prepended to PATH."""
    env = os.environ.copy()
    parts = env.get("PATH", "").split(os.pathsep)
    for directory in _GLOBAL_BIN_DIRS:
        as_str = str(directory)
        if as_str not in parts:
            parts.insert(0, as_str)
    env["PATH"] = os.pathsep.join(parts)
    return env


def find_worker_bin(name: str) -> str | None:
    """Locate a worker CLI on PATH or in the common global-bin dirs."""
    found = shutil.which(name, path=worker_env()["PATH"])
    if found:
        return found
    for directory in _GLOBAL_BIN_DIRS:
        candidate = directory / name
        if candidate.exists():
            return str(candidate)
    return None
