from __future__ import annotations

from pathlib import Path

from app.core.repo_graph import RepoGraphBuilder


def test_repo_graph_builder_scans_sample_fastapi_app() -> None:
    graph = RepoGraphBuilder().build(Path("examples/sample_fastapi_app"))

    node_ids = {node.id for node in graph.nodes}
    edge_types = {edge.type for edge in graph.edges}

    assert graph.summary.languages == ["python"]
    assert "fastapi" in graph.summary.frameworks
    assert "file:app/main.py" in node_ids
    assert any(node.type == "import" and "fastapi" in node.name for node in graph.nodes)
    assert any(node.type == "dependency" and node.name == "fastapi" for node in graph.nodes)
    assert any(node.type == "test" and node.path == "tests/test_health.py" for node in graph.nodes)
    assert "likely_tests" in edge_types


def test_repo_graph_builder_detects_java_spring_migration_risks(tmp_path: Path) -> None:
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
        "  @GetMapping(\"/users\")\n"
        "  public String users() { return \"ok\"; }\n"
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

    node_ids = {node.id for node in graph.nodes}
    risk_names = {node.name for node in graph.nodes if node.type == "migration_risk"}

    assert "java" in graph.summary.languages
    assert "spring" in graph.summary.frameworks
    assert "spring_boot" in graph.summary.frameworks
    assert "route:java:GET:/users" in node_ids
    assert "javax_to_jakarta_required" in risk_names
    assert "spring_boot_2_detected" in risk_names
    assert "java_version_below_17" in risk_names
