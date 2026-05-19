from pathlib import Path

from app.core.test_runner import TestRunner


def test_test_runner_captures_pytest_success(tmp_path: Path) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok():\n    assert 1 + 1 == 2\n")

    summary = TestRunner().run(tmp_path, commands=["python -m pytest -q"])

    assert summary.passed is True
    assert summary.commands[0].exit_code == 0
    assert "passed" in summary.commands[0].stdout
