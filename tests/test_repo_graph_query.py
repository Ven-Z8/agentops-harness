from __future__ import annotations

from pathlib import Path

from app.core.repo_graph import RepoGraphBuilder, RepoGraphQuery


def test_repo_graph_query_extracts_planner_context() -> None:
    graph = RepoGraphBuilder().build(Path("examples/sample_fastapi_app"))
    context = RepoGraphQuery(graph).planner_context()

    assert "fastapi" in context.frameworks
    assert "app/main.py" in context.entrypoint_candidates
    assert "tests/test_health.py" in context.test_files
    assert "fastapi" in context.dependencies
    assert "uv run pytest -q" in context.validation_commands


def test_repo_graph_query_localizes_routes_and_likely_tests() -> None:
    query = RepoGraphQuery(RepoGraphBuilder().build(Path("examples/sample_fastapi_app")))

    assert "app/main.py" in query.route_files()
    assert "GET /health" in query.route_names()
    likely = query.likely_tests_for_files(["app/main.py"])
    assert all(path.startswith("tests/") for path in likely)


def test_validation_commands_prefer_uv_for_pyproject_repo() -> None:
    query = RepoGraphQuery(RepoGraphBuilder().build(Path("examples/sample_fastapi_app")))

    assert query.validation_commands() == ["uv run pytest -q", "uv run ruff check ."]


def test_validation_commands_plain_python_without_pyproject(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")

    query = RepoGraphQuery(RepoGraphBuilder().build(repo))

    assert query.validation_commands() == ["python -m pytest -q", "ruff check ."]


def test_validation_commands_maven(tmp_path: Path) -> None:
    repo = tmp_path / "maven_app"
    repo.mkdir()
    (repo / "pom.xml").write_text(
        "<project><dependencies></dependencies></project>", encoding="utf-8"
    )

    query = RepoGraphQuery(RepoGraphBuilder().build(repo))

    assert query.validation_commands() == ["mvn test"]


def test_validation_commands_gradle_wrapper(tmp_path: Path) -> None:
    repo = tmp_path / "gradle_app"
    repo.mkdir()
    (repo / "build.gradle").write_text(
        "plugins { id 'org.springframework.boot' version '3.2.0' }\n", encoding="utf-8"
    )
    (repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

    query = RepoGraphQuery(RepoGraphBuilder().build(repo))

    assert query.validation_commands() == ["./gradlew test"]


def test_validation_commands_gradle_without_wrapper(tmp_path: Path) -> None:
    repo = tmp_path / "gradle_app"
    repo.mkdir()
    (repo / "build.gradle").write_text(
        "plugins { id 'org.springframework.boot' version '3.2.0' }\n", encoding="utf-8"
    )

    query = RepoGraphQuery(RepoGraphBuilder().build(repo))

    assert query.validation_commands() == ["gradle test"]
