from app.core.security import is_sensitive_path
from app.schemas.risk import RiskReport
from app.schemas.test import TestRunSummary


class RiskGuard:
    def assess(
        self,
        changed_files: list[str],
        deleted_files: list[str],
        test_results: TestRunSummary,
    ) -> RiskReport:
        score = 0
        factors: list[str] = []

        file_count = len(changed_files)
        if file_count:
            score += min(file_count * 4, 25)
            factors.append(f"{file_count} changed file(s)")

        sensitive_files = [path for path in changed_files if is_sensitive_path(path)]
        if sensitive_files:
            score += 70
            factors.append(f"Sensitive file touched: {', '.join(sensitive_files)}")

        dependency_files = [
            path
            for path in changed_files
            if path.endswith(("pyproject.toml", "uv.lock", "requirements.txt"))
        ]
        if dependency_files:
            score += 20
            factors.append(f"Dependency/config change: {', '.join(dependency_files)}")

        if deleted_files:
            score += min(len(deleted_files) * 10, 30)
            factors.append(f"{len(deleted_files)} deleted file(s)")

        if not test_results.passed:
            score += 35
            factors.append("One or more validation commands failed")

        if changed_files and not any(path.startswith("tests/") for path in changed_files):
            score += 10
            factors.append("No tests changed")

        score = min(score, 100)
        level = self._level(score)
        return RiskReport(
            risk_score=score,
            risk_level=level,
            factors=factors or ["No material risk factors detected"],
            blocked=level == "critical",
        )

    def _level(self, score: int) -> str:
        if score >= 80:
            return "critical"
        if score >= 55:
            return "high"
        if score >= 30:
            return "medium"
        return "low"

