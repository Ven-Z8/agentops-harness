from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.core.repo_graph.models import RepoGraph, RepoGraphEdge, RepoGraphNode
from app.core.repo_graph.python_parser import PythonParser
from app.core.repo_graph.query import RepoGraphQuery


class ImpactedNode(BaseModel):
    id: str
    type: str
    name: str
    path: str | None = None
    reason: str
    metadata: dict = Field(default_factory=dict)


class ImpactedRoute(BaseModel):
    method: str
    path: str
    source_file: str | None = None
    node_id: str


class ImpactedValidation(BaseModel):
    command: str
    reason: str


class ChangedSubgraph(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    impacted_nodes: list[ImpactedNode] = Field(default_factory=list)
    impacted_routes: list[ImpactedRoute] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    recommended_validation: list[ImpactedValidation] = Field(default_factory=list)

    @property
    def has_impact(self) -> bool:
        return bool(self.changed_files or self.deleted_files)


class ChangedSubgraphBuilder:
    """Map git changes back to deterministic RepoGraph structure."""

    def build(
        self,
        graph: RepoGraph,
        *,
        changed_files: list[str],
        deleted_files: list[str],
        fallback_validation: list[str],
        repo_path: Path | None = None,
    ) -> ChangedSubgraph:
        query = RepoGraphQuery(graph)
        nodes_by_id = {node.id: node for node in graph.nodes}
        edge_index = _EdgeIndex(graph.edges)

        normalized_changed = _unique(_normalize_path(path) for path in changed_files)
        normalized_deleted = _unique(_normalize_path(path) for path in deleted_files)

        impacted_nodes: list[ImpactedNode] = []
        impacted_routes: list[ImpactedRoute] = []
        dependencies: list[str] = []
        risk_notes: list[str] = []

        for path in normalized_changed:
            file_node = nodes_by_id.get(self._file_id(path))
            if file_node is not None:
                impacted_nodes.append(_impact_node(file_node, "changed_file"))

            for defined_node in self._defined_nodes(file_node, edge_index, nodes_by_id):
                impacted_nodes.append(_impact_node(defined_node, "defined_by_changed_file"))
                for route in self._routes_exposed_by(defined_node, edge_index, nodes_by_id):
                    impacted_routes.append(_impact_route(route))
                    impacted_nodes.append(_impact_node(route, "route_exposed_by_changed_file"))

            for imported in self._imports_for_file(file_node, edge_index, nodes_by_id):
                dependencies.append(imported.name)
                impacted_nodes.append(_impact_node(imported, "imported_by_changed_file"))

            for risk in self._risks_for_file(file_node, edge_index, nodes_by_id):
                risk_notes.append(_risk_note(risk))
                impacted_nodes.append(_impact_node(risk, "risk_attached_to_changed_file"))

        # The repo graph is built from the PRE-edit snapshot, so routes a worker ADDS in
        # its diff are absent from it. Re-parse the changed files' current content to surface
        # them, otherwise the Evidence Guard false-flags the new route as an ungrounded claim.
        if repo_path is not None:
            impacted_routes.extend(
                self._routes_added_by_change(repo_path, normalized_changed)
            )

        for path in normalized_deleted:
            risk_notes.append(f"Deleted file requires review: {path}")

        route_files = {route.source_file for route in impacted_routes if route.source_file}
        related_tests = query.likely_tests_for_files(normalized_changed)
        if not related_tests and route_files:
            related_tests = query.likely_tests_for_files(sorted(route_files))

        return ChangedSubgraph(
            changed_files=normalized_changed,
            deleted_files=normalized_deleted,
            impacted_nodes=_unique_impacted_nodes(impacted_nodes),
            impacted_routes=_unique_routes(impacted_routes),
            related_tests=related_tests,
            dependencies=_unique(dependencies),
            risk_notes=_unique(risk_notes),
            recommended_validation=self._recommended_validation(
                query=query,
                related_tests=related_tests,
                fallback_validation=fallback_validation,
            ),
        )

    def _defined_nodes(
        self,
        file_node: RepoGraphNode | None,
        edge_index: _EdgeIndex,
        nodes_by_id: dict[str, RepoGraphNode],
    ) -> list[RepoGraphNode]:
        if file_node is None:
            return []
        return [
            nodes_by_id[edge.target]
            for edge in edge_index.outgoing(file_node.id, "defines")
            if edge.target in nodes_by_id
        ]

    def _routes_exposed_by(
        self,
        defined_node: RepoGraphNode,
        edge_index: _EdgeIndex,
        nodes_by_id: dict[str, RepoGraphNode],
    ) -> list[RepoGraphNode]:
        return [
            nodes_by_id[edge.target]
            for edge in edge_index.outgoing(defined_node.id, "exposes_route")
            if edge.target in nodes_by_id
        ]

    def _routes_added_by_change(
        self, repo_path: Path, changed_files: list[str]
    ) -> list[ImpactedRoute]:
        parser = PythonParser()
        added: list[ImpactedRoute] = []
        for path in changed_files:
            if not path.endswith(".py"):
                continue
            try:
                result = parser.parse(repo_path, path)
            except (OSError, ValueError):
                # PythonParser.parse swallows SyntaxError itself; OSError (unreadable file)
                # and ValueError (e.g. null bytes in source) can still propagate.
                continue
            for route in result.routes:
                # node_id matches the graph builder's scheme so _unique_routes dedups any
                # route the pre-edit graph already exposed; only genuinely-new ones survive.
                added.append(
                    ImpactedRoute(
                        method=route.method,
                        path=route.path,
                        source_file=path,
                        node_id=f"route:python:{route.method}:{route.path}",
                    )
                )
        return added

    def _imports_for_file(
        self,
        file_node: RepoGraphNode | None,
        edge_index: _EdgeIndex,
        nodes_by_id: dict[str, RepoGraphNode],
    ) -> list[RepoGraphNode]:
        if file_node is None:
            return []
        return [
            nodes_by_id[edge.target]
            for edge in edge_index.outgoing(file_node.id, "imports")
            if edge.target in nodes_by_id
        ]

    def _risks_for_file(
        self,
        file_node: RepoGraphNode | None,
        edge_index: _EdgeIndex,
        nodes_by_id: dict[str, RepoGraphNode],
    ) -> list[RepoGraphNode]:
        if file_node is None:
            return []
        return [
            nodes_by_id[edge.target]
            for edge in edge_index.outgoing(file_node.id, "has_risk")
            if edge.target in nodes_by_id
        ]

    def _recommended_validation(
        self,
        *,
        query: RepoGraphQuery,
        related_tests: list[str],
        fallback_validation: list[str],
    ) -> list[ImpactedValidation]:
        validation_commands = query.validation_commands()
        if not related_tests:
            return [
                ImpactedValidation(command=command, reason="planner_validation_fallback")
                for command in fallback_validation
            ]

        recommendations: list[ImpactedValidation] = []
        if any(command.startswith("uv run pytest") for command in validation_commands):
            recommendations.append(
                ImpactedValidation(
                    command=f"uv run pytest {' '.join(related_tests)} -q",
                    reason="related_tests_from_repo_graph",
                )
            )
        elif any(command.startswith("python -m pytest") for command in validation_commands):
            recommendations.append(
                ImpactedValidation(
                    command=f"python -m pytest {' '.join(related_tests)} -q",
                    reason="related_tests_from_repo_graph",
                )
            )
        elif "mvn test" in validation_commands:
            test_classes = _java_test_classes(related_tests)
            command = f"mvn test -Dtest={','.join(test_classes)}" if test_classes else "mvn test"
            recommendations.append(
                ImpactedValidation(command=command, reason="related_tests_from_repo_graph")
            )

        for command in validation_commands:
            if "ruff check" in command:
                recommendations.append(
                    ImpactedValidation(command=command, reason="style_validation_from_planner")
                )

        return recommendations or [
            ImpactedValidation(command=command, reason="planner_validation_fallback")
            for command in fallback_validation
        ]

    def _file_id(self, relative_path: str) -> str:
        return f"file:{relative_path}"


class _EdgeIndex:
    def __init__(self, edges: list[RepoGraphEdge]) -> None:
        self.edges = edges

    def outgoing(self, source: str, edge_type: str) -> list[RepoGraphEdge]:
        return [edge for edge in self.edges if edge.source == source and edge.type == edge_type]


def _impact_node(node: RepoGraphNode, reason: str) -> ImpactedNode:
    return ImpactedNode(
        id=node.id,
        type=node.type,
        name=node.name,
        path=node.path,
        reason=reason,
        metadata=node.metadata,
    )


def _impact_route(node: RepoGraphNode) -> ImpactedRoute:
    return ImpactedRoute(
        method=str(node.metadata.get("method", "")),
        path=str(node.metadata.get("path", node.name)),
        source_file=node.path,
        node_id=node.id,
    )


def _risk_note(node: RepoGraphNode) -> str:
    severity = node.metadata.get("severity", "medium")
    reason = node.metadata.get("reason", "Detected by repo graph scan.")
    return f"Graph risk [{severity}] {node.name}: {reason}"


def _normalize_path(path: str) -> str:
    return Path(path).as_posix()


def _java_test_classes(paths: list[str]) -> list[str]:
    return [Path(path).stem for path in paths if path.endswith(".java")]


def _unique(items) -> list:
    seen = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _unique_impacted_nodes(nodes: list[ImpactedNode]) -> list[ImpactedNode]:
    seen: set[tuple[str, str]] = set()
    ordered: list[ImpactedNode] = []
    for node in nodes:
        key = (node.id, node.reason)
        if key not in seen:
            seen.add(key)
            ordered.append(node)
    return ordered


def _unique_routes(routes: list[ImpactedRoute]) -> list[ImpactedRoute]:
    seen: set[str] = set()
    ordered: list[ImpactedRoute] = []
    for route in routes:
        if route.node_id not in seen:
            seen.add(route.node_id)
            ordered.append(route)
    return ordered


def render_changed_subgraph_markdown(changed_subgraph: ChangedSubgraph) -> str:
    if not changed_subgraph.has_impact:
        return (
            "\n\n## Impacted Area\n\n"
            "No changed files were detected; no graph impact was computed.\n"
        )

    lines = ["", "", "## Impacted Area", "", "Changed files:"]
    lines.extend(f"- `{path}`" for path in changed_subgraph.changed_files)
    if changed_subgraph.deleted_files:
        lines.extend(["", "Deleted files:"])
        lines.extend(f"- `{path}`" for path in changed_subgraph.deleted_files)

    if changed_subgraph.impacted_routes:
        lines.extend(["", "Impacted routes:"])
        lines.extend(
            f"- `{route.method} {route.path}` ({route.source_file or 'unknown file'})"
            for route in changed_subgraph.impacted_routes
        )

    if changed_subgraph.related_tests:
        lines.extend(["", "Related tests:"])
        lines.extend(f"- `{path}`" for path in changed_subgraph.related_tests)

    if changed_subgraph.risk_notes:
        lines.extend(["", "Graph risk notes:"])
        lines.extend(f"- {note}" for note in changed_subgraph.risk_notes)

    if changed_subgraph.recommended_validation:
        lines.extend(["", "Recommended targeted validation:"])
        lines.extend(
            f"- `{item.command}` ({item.reason})"
            for item in changed_subgraph.recommended_validation
        )

    return "\n".join(lines) + "\n"
