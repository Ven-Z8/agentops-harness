from __future__ import annotations

import os
from pathlib import Path

import pytest

# AO-D01-01: hermetic test environment.
#
# ``openhands.sdk`` imports ``litellm``, whose ``__init__`` calls
# ``dotenv.load_dotenv()`` when ``LITELLM_MODE`` is unset or "DEV" (its default).
# That call reads the CWD ``.env`` (the developer's real credentials) and writes
# every entry into ``os.environ`` at import time — before any test runs and
# outside monkeypatch control. Ambient repository configuration then leaks into
# every test that constructs Settings or asserts provider defaults, and results
# differ by machine.
#
# Setting LITELLM_MODE to anything other than "DEV" skips that load entirely.
# The suite stays deterministic and developer credentials are never read.
if os.environ.get("LITELLM_MODE", "DEV") == "DEV":
    os.environ.setdefault("LITELLM_MODE", "")  # not "DEV" → litellm skips load_dotenv


@pytest.fixture
def chdir(monkeypatch: pytest.MonkeyPatch) -> object:
    """Return a chdir helper that restores the original CWD on teardown.

    Usage::

        def test_x(chdir, tmp_path):
            chdir(tmp_path)

    The original directory is restored even if the test fails, so one test
    can never leak a working-directory change into the rest of the suite.
    """

    original = Path.cwd()

    def _chdir(target: Path) -> None:
        monkeypatch.chdir(target)

    yield _chdir
    monkeypatch.chdir(original)
