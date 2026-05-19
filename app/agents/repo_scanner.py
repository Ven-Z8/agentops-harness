from __future__ import annotations

from pathlib import Path

from app.schemas.repo import RepoProfile


class RepoScanner:
    PYTHON_CONFIGS = ("pyproject.toml", "setup.py", "requirements.txt")

    def scan(self, repo_path: Path) -> RepoProfile:
        resolved = repo_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        files = [
            path for path in resolved.rglob("*") if path.is_file() and ".venv" not in path.parts
        ]
        relative_files = sorted(path.relative_to(resolved).as_posix() for path in files)
        python_files = [path for path in relative_files if path.endswith(".py")]
        config_files = [path for path in relative_files if self._is_config_file(path)]
        has_python_config = any(path in relative_files for path in self.PYTHON_CONFIGS)

        return RepoProfile(
            repo_path=str(resolved),
            language="python" if python_files or has_python_config else None,
            framework=self._detect_framework(resolved, relative_files),
            package_manager=self._detect_package_manager(relative_files),
            test_framework="pytest" if self._has_pytest(relative_files) else None,
            entrypoints=self._detect_entrypoints(resolved, relative_files),
            important_folders=self._detect_important_folders(resolved),
            config_files=config_files,
            source_files=python_files[:200],
        )

    def _detect_framework(self, repo_path: Path, relative_files: list[str]) -> str | None:
        pyproject = repo_path / "pyproject.toml"
        if pyproject.exists() and "fastapi" in pyproject.read_text(encoding="utf-8").lower():
            return "fastapi"

        for path in relative_files:
            if not path.endswith(".py"):
                continue
            text = (repo_path / path).read_text(encoding="utf-8", errors="ignore").lower()
            if "from fastapi import" in text or "fastapi(" in text:
                return "fastapi"
        return None

    def _detect_package_manager(self, relative_files: list[str]) -> str | None:
        if "uv.lock" in relative_files or "pyproject.toml" in relative_files:
            return "uv"
        if "requirements.txt" in relative_files:
            return "pip"
        return None

    def _has_pytest(self, relative_files: list[str]) -> bool:
        return any(path.startswith("tests/") and path.endswith(".py") for path in relative_files)

    def _detect_entrypoints(self, repo_path: Path, relative_files: list[str]) -> list[str]:
        entrypoints: list[str] = []
        for candidate in ("app/main.py", "main.py", "src/main.py"):
            if candidate in relative_files:
                entrypoints.append(candidate)

        for path in relative_files:
            if not path.endswith(".py") or path in entrypoints:
                continue
            text = (repo_path / path).read_text(encoding="utf-8", errors="ignore")
            if "FastAPI(" in text or 'if __name__ == "__main__"' in text:
                entrypoints.append(path)
        return sorted(set(entrypoints))

    def _detect_important_folders(self, repo_path: Path) -> list[str]:
        candidates = ["app", "src", "tests", "scripts", "docs"]
        return [folder for folder in candidates if (repo_path / folder).is_dir()]

    def _is_config_file(self, path: str) -> bool:
        name = Path(path).name
        return name in {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "Makefile",
        } or path.startswith(".github/")
