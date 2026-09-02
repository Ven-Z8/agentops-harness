from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers_project_control import make_control_room_state


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def control_room_state():
    return make_control_room_state()
