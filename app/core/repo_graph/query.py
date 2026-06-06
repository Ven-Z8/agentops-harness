from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.core.repo_graph.models import RepoGraph, RepoGraphNode

_FILE_LIKE_TYPES = {"file", "test", "config"}
_ENTRYPOINT_BASENAMES = {
    "main.py",
    "app.py",
    "__main__.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "application.java",
}


class GraphPlannerContext(BaseModel):
    """Compact, deterministic projection of a RepoGraph for planning prompts."""

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    build_tools: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    entrypoint_candidates: list[str] = Field(default_factory=list)
    route_files: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)


class RepoGraphQuery:
    """Deterministic read-side helpers over a RepoGraph.

    This layer never calls an LLM and never re-reads the filesystem; every
    answer is derived from nodes/edges produced by ``RepoGraphBuilder``. It
    localizes candidate files, tests, routes, dependencies, and risks so the
    planner can ground its plan in repository structure (LocAgent-style
    deterministic localization).
    """

    def __init__(self, graph: RepoGraph) -> None:
        self.graph = graph
        self._nodes_by_id: dict[str, RepoGraphNode] = {node.id: node for node in graph.nodes}

    def files(self) -> list[RepoGraphNode]:
        return [node for node in self.graph.nodes if node.type in _FILE_LIKE_TYPES]

    def source_files(self) -> list[str]:
        return [
            node.path
            for node in self.graph.nodes
            if node.type in {"file", "config"} and node.language is not None and node.path
        ]

    def test_files(self) -> list[str]:
        return [node.path for node in self.graph.nodes if node.type == "test" and node.path]

    def config_files(self) -> list[str]:
        return [node.path for node in self.graph.nodes if node.type == "config" and node.path]

    def routes(self) -> list[RepoGraphNode]:
        return [node for node in self.graph.nodes if node.type == "route"]

    def route_files(self) -> list[str]:
        return _unique(node.path for node in self.routes() if node.path)

    def route_names(self) -> list[str]:
        return _unique(node.name for node in self.routes() if node.name)

    def dependency_names(self) -> list[str]:
        return _unique(node.name for node in self.graph.nodes if node.type == "dependency")

    def risk_nodes(self) -> list[RepoGraphNode]:
        return [node for node in self.graph.nodes if node.type == "migration_risk"]

    def risk_notes(self) -> list[str]:
        notes: list[str] = []
        for node in self.risk_nodes():
            severity = node.metadata.get("severity", "medium")
            reason = node.metadata.get("reason", "Detected by repo graph scan.")
            notes.append(f"Graph risk [{severity}] {node.name}: {reason}")
        return notes

    def likely_tests_for_files(self, files: list[str]) -> list[str]:
        """Return test files whose ``likely_tests`` edge points at any of ``files``."""
        targets = {self._file_id(path) for path in files}
        tests: list[str] = []
        for edge in self.graph.edges:
            if edge.type != "likely_tests" or edge.target not in targets:
                continue
            test_node = self._nodes_by_id.get(edge.source)
            if test_node and test_node.path:
                tests.append(test_node.path)
        return _unique(tests)

    def entrypoint_candidates(self) -> list[str]:
        candidates = list(self.route_files())
        for node in self.graph.nodes:
            if node.type not in {"file", "config"} or not node.path:
                continue
            if Path(node.path).name in _ENTRYPOINT_BASENAMES:
                candidates.append(node.path)
        return _unique(candidates)

    def validation_commands(self) -> list[str]:
        build_tools = set(self.graph.summary.build_tools)
        languages = set(self.graph.summary.languages)

        if "maven" in build_tools:
            return ["mvn test"]
        if "gradle" in build_tools:
            if self._has_file_named("gradlew"):
                return ["./gradlew test"]
            return ["gradle test"]
        if "python" in languages or {"pyproject", "pip"} & build_tools:
            if self._is_uv_project(build_tools):
                return ["uv run pytest -q", "uv run ruff check ."]
            return ["python -m pytest -q", "ruff check ."]
        return []

    def planner_context(self) -> GraphPlannerContext:
        return GraphPlannerContext(
            languages=list(self.graph.summary.languages),
            frameworks=list(self.graph.summary.frameworks),
            build_tools=list(self.graph.summary.build_tools),
            test_frameworks=list(self.graph.summary.test_frameworks),
            entrypoint_candidates=self.entrypoint_candidates(),
            route_files=self.route_files(),
            routes=self.route_names(),
            test_files=self.test_files(),
            dependencies=self.dependency_names(),
            risks=self.risk_notes(),
            validation_commands=self.validation_commands(),
        )

    def _is_uv_project(self, build_tools: set[str]) -> bool:
        if self._has_file_named("uv.lock"):
            return True
        # pyproject-managed repos default to uv per harness conventions; plain
        # requirements.txt-only repos fall back to the stdlib invocation.
        return "pyproject" in build_tools

    def _has_file_named(self, name: str) -> bool:
        return any(
            node.path and Path(node.path).name == name
            for node in self.graph.nodes
            if node.type in _FILE_LIKE_TYPES
        )

    def _file_id(self, relative_path: str) -> str:
        return f"file:{relative_path}"


def _unique(items) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
