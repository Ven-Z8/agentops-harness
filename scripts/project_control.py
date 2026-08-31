#!/usr/bin/env python3
"""Thin executable wrapper for the Project Control Room CLI."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

main = import_module("app.project_control.cli").main


if __name__ == "__main__":
    raise SystemExit(main())
