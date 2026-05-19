from app.agents.risk_guard import RiskGuard
from app.schemas.test import CommandResult, TestRunSummary


def passing_tests() -> TestRunSummary:
    return TestRunSummary(
        commands=[
            CommandResult(
                command="pytest",
                exit_code=0,
                duration_seconds=0.1,
                stdout="1 passed",
                stderr="",
            )
        ]
    )


def test_risk_guard_marks_sensitive_file_as_critical() -> None:
    report = RiskGuard().assess(
        changed_files=[".env", "app/main.py"],
        deleted_files=[],
        test_results=passing_tests(),
    )

    assert report.risk_level == "critical"
    assert report.blocked is True
    assert any("Sensitive file touched" in factor for factor in report.factors)


def test_risk_guard_scores_low_for_small_passing_change() -> None:
    report = RiskGuard().assess(
        changed_files=["app/main.py", "tests/test_main.py"],
        deleted_files=[],
        test_results=passing_tests(),
    )

    assert report.risk_level == "low"
    assert report.blocked is False
    assert report.risk_score < 30
