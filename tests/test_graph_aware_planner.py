from __future__ import annotations

from pathlib import Path

from app.agents.planner import Planner
from app.core.repo_graph import RepoGraphBuilder
from app.schemas.repo import RepoProfile


def _fastapi_profile() -> RepoProfile:
    return RepoProfile(
        repo_path="examples/sample_fastapi_app",
        language="python",
        framework="fastapi",
        entrypoints=["app/main.py"],
        source_files=["app/main.py", "tests/test_health.py"],
    )


def test_planner_falls_back_without_graph() -> None:
    plan = Planner().create_plan("Add a route", _fastapi_profile())

    files = {path for step in plan.steps for path in step.files_to_inspect}
    assert "app/main.py" in files
    assert plan.tests_to_run == ["python -m pytest -q", "ruff check ."]


def test_planner_uses_fastapi_graph_context() -> None:
    graph = RepoGraphBuilder().build(Path("examples/sample_fastapi_app"))

    plan = Planner().create_plan("Add a route", _fastapi_profile(), repo_graph=graph)

    inspected = {path for step in plan.steps for path in step.files_to_inspect}
    assert "app/main.py" in inspected
    assert "uv run pytest -q" in plan.tests_to_run
    assert "uv run ruff check ." in plan.tests_to_run


def test_java_spring_risks_feed_planner(tmp_path: Path) -> None:
    repo = tmp_path / "spring_app"
    source = repo / "src/main/java/com/example/UserController.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package com.example;\n"
        "import javax.persistence.Entity;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.RestController;\n"
        "@RestController\n"
        "public class UserController {\n"
        '  @GetMapping("/users")\n'
        '  public String users() { return "ok"; }\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / "pom.xml").write_text(
        "<project>"
        "<parent>"
        "<groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-parent</artifactId>"
        "<version>2.7.18</version>"
        "</parent>"
        "<properties><java.version>11</java.version></properties>"
        "<dependencies>"
        "<dependency>"
        "<groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId>"
        "</dependency>"
        "</dependencies>"
        "</project>",
        encoding="utf-8",
    )

    graph = RepoGraphBuilder().build(repo)
    profile = RepoProfile(repo_path=str(repo), language="java", framework="spring")

    plan = Planner().create_plan("Migrate to Spring Boot 3", profile, repo_graph=graph)

    risk_text = "\n".join(plan.risk_notes)
    assert "Spring Boot 2" in risk_text
    assert "Java 17" in risk_text
    assert "Jakarta" in risk_text or "javax" in risk_text
    assert "mvn test" in plan.tests_to_run
