"""Finding E: a command that exceeds its timeout must be recorded as a failed
command, not crash the run.

Surfaced by a real run: `uv run pytest` on a cold uv project exceeded the
timeout, and the unhandled subprocess.TimeoutExpired killed the whole harness
run before any evidence was persisted — the opposite of the harness's promise
that a misbehaving step still yields usable evidence.
"""

from pathlib import Path

from app.core.test_runner import TestRunner


def test_timeout_is_recorded_as_failed_command_not_raised(tmp_path: Path) -> None:
    summary = TestRunner().run(
        tmp_path,
        commands=['python -c "import time; time.sleep(5)"'],
        timeout_seconds=1,
    )

    assert summary.passed is False
    result = summary.commands[0]
    assert result.exit_code != 0
    assert "timed out" in result.stderr.lower()


def test_timeout_does_not_block_subsequent_commands(tmp_path: Path) -> None:
    summary = TestRunner().run(
        tmp_path,
        commands=[
            'python -c "import time; time.sleep(5)"',
            'python -c "print(\'ok\')"',
        ],
        timeout_seconds=1,
    )

    assert len(summary.commands) == 2
    assert summary.commands[0].exit_code != 0
    assert summary.commands[1].exit_code == 0
