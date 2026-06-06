from __future__ import annotations

from pathlib import Path

from app.core.repo_graph.dependency_parser import DependencyParser
from app.core.repo_graph.java_parser import JavaParser
from app.core.repo_graph.models import RepoGraph, RepoGraphEdge, RepoGraphNode, RepoGraphSummary
from app.core.repo_graph.python_parser import PythonParser
from app.core.repo_graph.risk_mapper import RiskMapper
from app.core.repo_graph.test_mapper import TestMapper


class RepoGraphBuilder:
    IGNORED_PARTS = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
    }
    CONFIG_FILES = {
        ".env.example",
        "Dockerfile",
        "Makefile",
        "build.gradle",
        "build.gradle.kts",
        "docker-compose.yml",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
    }

    def __init__(self) -> None:
        self.python_parser = PythonParser()
        self.java_parser = JavaParser()
        self.dependency_parser = DependencyParser()
        self.test_mapper = TestMapper()
        self.risk_mapper = RiskMapper()
        self._nodes: dict[str, RepoGraphNode] = {}
        self._edges: dict[tuple[str, str, str], RepoGraphEdge] = {}

    def build(self, repo_path: Path) -> RepoGraph:
        resolved = repo_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        self._nodes = {}
        self._edges = {}
        files = [
            path
            for path in resolved.rglob("*")
            if path.is_file() and not self._is_ignored(path.relative_to(resolved))
        ]
        relative_files = sorted(path.relative_to(resolved).as_posix() for path in files)
        source_files: list[str] = []
        test_files: list[str] = []
        languages: set[str] = set()
        frameworks: set[str] = set()
        build_tools: set[str] = set()
        test_frameworks: set[str] = set()

        for relative_path in relative_files:
            language = self._language_for_path(relative_path)
            if language:
                languages.add(language)
                source_files.append(relative_path)
            file_type = "test" if self._looks_like_test(relative_path) else "file"
            if file_type == "test":
                test_files.append(relative_path)
            file_node_id = self._add_file_node(relative_path, language, file_type)
            self._add_folder_edges(relative_path, file_node_id)

            if Path(relative_path).name in self.CONFIG_FILES:
                self._nodes[file_node_id].type = "config"

            for risk in self.risk_mapper.risks_for_path(relative_path):
                self._add_risk(relative_path, risk)

            if relative_path.endswith(".py"):
                parsed = self.python_parser.parse(resolved, relative_path)
                if parsed.is_test and relative_path not in test_files:
                    test_files.append(relative_path)
                    self._nodes[file_node_id].type = "test"
                if parsed.uses_fastapi:
                    frameworks.add("fastapi")
                if parsed.is_test:
                    test_frameworks.add("pytest")
                self._add_python_parse(relative_path, parsed)
            elif relative_path.endswith(".java"):
                parsed = self.java_parser.parse(resolved, relative_path)
                if parsed.is_test and relative_path not in test_files:
                    test_files.append(relative_path)
                    self._nodes[file_node_id].type = "test"
                if parsed.is_spring:
                    frameworks.add("spring")
                self._add_java_parse(relative_path, parsed)

        dependencies = self.dependency_parser.parse(resolved, relative_files)
        frameworks.update(dependencies.frameworks)
        build_tools.update(dependencies.build_tools)
        for dependency in dependencies.dependencies:
            self._add_dependency(
                dependency.name,
                dependency.ecosystem,
                dependency.source,
                dependency.version,
            )
        for risk in dependencies.risks:
            self._add_risk(None, risk)

        self._add_likely_test_edges(test_files, source_files)
        risks = [node for node in self._nodes.values() if node.type == "migration_risk"]
        graph = RepoGraph(
            repo_path=str(resolved),
            summary=RepoGraphSummary(
                languages=sorted(languages),
                frameworks=sorted(frameworks),
                build_tools=sorted(build_tools),
                test_frameworks=sorted(test_frameworks),
                source_file_count=len(source_files),
                test_file_count=len(set(test_files)),
                dependency_count=len(
                    [node for node in self._nodes.values() if node.type == "dependency"]
                ),
                risk_count=len(risks),
            ),
            nodes=sorted(self._nodes.values(), key=lambda node: node.id),
            edges=sorted(
                self._edges.values(),
                key=lambda edge: (edge.source, edge.type, edge.target),
            ),
        )
        return graph

    def _add_python_parse(self, relative_path: str, parsed) -> None:
        file_node_id = self._file_id(relative_path)
        for imported in parsed.imports:
            import_id = f"import:python:{imported.name}"
            self._add_node(
                RepoGraphNode(
                    id=import_id,
                    type="import",
                    name=imported.name,
                    language="python",
                    metadata={"imported_from": imported.imported_from},
                )
            )
            self._add_edge(file_node_id, import_id, "imports")
        for symbol in parsed.symbols:
            symbol_id = f"{symbol.symbol_type}:python:{symbol.qualified_name}"
            self._add_node(
                RepoGraphNode(
                    id=symbol_id,
                    type=symbol.symbol_type,
                    name=symbol.name,
                    path=relative_path,
                    language="python",
                    metadata={"qualified_name": symbol.qualified_name, "line": symbol.line},
                )
            )
            self._add_edge(file_node_id, symbol_id, "defines")
        for route in parsed.routes:
            route_id = f"route:python:{route.method}:{route.path}"
            self._add_node(
                RepoGraphNode(
                    id=route_id,
                    type="route",
                    name=f"{route.method} {route.path}",
                    path=relative_path,
                    language="python",
                    metadata={"method": route.method, "path": route.path, "line": route.line},
                )
            )
            module_name = self.python_parser._module_name(relative_path)
            function_id = f"function:python:{module_name}.{route.function_name}"
            self._add_edge(function_id, route_id, "exposes_route")

    def _add_java_parse(self, relative_path: str, parsed) -> None:
        file_node_id = self._file_id(relative_path)
        for imported in parsed.imports:
            import_id = f"import:java:{imported}"
            self._add_node(
                RepoGraphNode(id=import_id, type="import", name=imported, language="java")
            )
            self._add_edge(file_node_id, import_id, "imports")
        for class_info in parsed.classes:
            class_id = f"class:java:{class_info.qualified_name}"
            self._add_node(
                RepoGraphNode(
                    id=class_id,
                    type="class",
                    name=class_info.name,
                    path=relative_path,
                    language="java",
                    metadata={
                        "qualified_name": class_info.qualified_name,
                        "class_type": class_info.class_type,
                        "annotations": class_info.annotations,
                        "line": class_info.line,
                    },
                )
            )
            self._add_edge(file_node_id, class_id, "defines")
        for route in parsed.routes:
            route_id = f"route:java:{route.method}:{route.path}"
            self._add_node(
                RepoGraphNode(
                    id=route_id,
                    type="route",
                    name=f"{route.method} {route.path}",
                    path=relative_path,
                    language="java",
                    metadata={"method": route.method, "path": route.path, "line": route.line},
                )
            )
            owner_id = f"class:java:{route.owner}"
            self._add_edge(owner_id, route_id, "exposes_route")
        for risk in parsed.risks:
            self._add_risk(relative_path, risk)

    def _add_dependency(
        self,
        name: str,
        ecosystem: str,
        source: str | None,
        version: str | None,
    ) -> None:
        dependency_id = f"dependency:{ecosystem}:{name}"
        self._add_node(
            RepoGraphNode(
                id=dependency_id,
                type="dependency",
                name=name,
                language=ecosystem,
                metadata={"source": source, "version": version},
            )
        )
        if source:
            config_path = source
            if config_path in self._nodes_by_path():
                self._add_edge(self._file_id(config_path), dependency_id, "declares_dependency")

    def _add_likely_test_edges(self, test_files: list[str], source_files: list[str]) -> None:
        production_files = [path for path in source_files if path not in set(test_files)]
        for test_file in sorted(set(test_files)):
            source = self.test_mapper.likely_source_for_test(test_file, production_files)
            if source:
                self._add_edge(self._file_id(test_file), self._file_id(source), "likely_tests")

    def _add_file_node(self, relative_path: str, language: str | None, node_type: str) -> str:
        node_id = self._file_id(relative_path)
        self._add_node(
            RepoGraphNode(
                id=node_id,
                type=node_type,
                name=Path(relative_path).name,
                path=relative_path,
                language=language,
            )
        )
        return node_id

    def _add_folder_edges(self, relative_path: str, file_node_id: str) -> None:
        parent_id = "folder:."
        self._add_node(RepoGraphNode(id=parent_id, type="folder", name=".", path="."))
        parts = Path(relative_path).parts[:-1]
        current_parts: list[str] = []
        for part in parts:
            current_parts.append(part)
            folder_path = "/".join(current_parts)
            folder_id = f"folder:{folder_path}"
            self._add_node(
                RepoGraphNode(id=folder_id, type="folder", name=part, path=folder_path)
            )
            self._add_edge(parent_id, folder_id, "contains")
            parent_id = folder_id
        self._add_edge(parent_id, file_node_id, "contains")

    def _add_risk(self, relative_path: str | None, risk_name: str) -> None:
        risk = self.risk_mapper.describe(risk_name)
        risk_id = f"risk:{risk.name}"
        self._add_node(
            RepoGraphNode(
                id=risk_id,
                type="migration_risk",
                name=risk.name,
                path=relative_path,
                metadata={"severity": risk.severity, "reason": risk.reason},
            )
        )
        if relative_path:
            self._add_edge(self._file_id(relative_path), risk_id, "has_risk")

    def _add_node(self, node: RepoGraphNode) -> None:
        if node.id not in self._nodes:
            self._nodes[node.id] = node

    def _add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        metadata: dict | None = None,
    ) -> None:
        key = (source, target, edge_type)
        if key not in self._edges:
            self._edges[key] = RepoGraphEdge(
                source=source,
                target=target,
                type=edge_type,
                metadata=metadata or {},
            )

    def _language_for_path(self, relative_path: str) -> str | None:
        suffix = Path(relative_path).suffix
        if suffix == ".py":
            return "python"
        if suffix == ".java":
            return "java"
        return None

    def _looks_like_test(self, relative_path: str) -> bool:
        name = Path(relative_path).name
        return (
            relative_path.startswith("tests/")
            or "/src/test/" in f"/{relative_path}"
            or name.startswith("test_")
            or name.endswith("_test.py")
            or name.endswith("Test.java")
            or name.endswith("Tests.java")
        )

    def _is_ignored(self, relative_path: Path) -> bool:
        return bool(set(relative_path.parts).intersection(self.IGNORED_PARTS))

    def _file_id(self, relative_path: str) -> str:
        return f"file:{relative_path}"

    def _nodes_by_path(self) -> set[str]:
        return {node.path for node in self._nodes.values() if node.path}
