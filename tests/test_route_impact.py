"""M2 — route-impact evidence fidelity.

The changed-subgraph builder must detect routes the worker *added* (so the
Evidence Guard stops false-flagging them) and scope impacted routes to the
diff-touched ones (so it stops over-including untouched routes in a changed file).
"""

from pathlib import Path

from app.agents.evidence_guard import EvidenceGuard
from app.core.repo_graph.impact import ChangedSubgraphBuilder
from app.core.repo_graph.models import RepoGraph, RepoGraphNode
from app.core.repo_graph.python_parser import PythonParser
from app.schemas.report import FinalReport
from app.schemas.test import TestRunSummary

_TWO_ROUTES = (
    "from fastapi import FastAPI\n"
    "\n"
    "app = FastAPI()\n"
    "\n"
    "@app.get('/existing')\n"
    "def existing():\n"
    "    return {'ok': True}\n"
    "\n"
    "@app.get('/health')\n"
    "def health():\n"
    "    return {'status': 'ok'}\n"
)


def _write_app(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "main.py").write_text(body, encoding="utf-8")
    return repo


def _route_node(method: str, path: str) -> RepoGraphNode:
    return RepoGraphNode(
        id=f"route:python:{method}:{path}",
        type="route",
        name=f"{method} {path}",
        path="app/main.py",
        metadata={"method": method, "path": path},
    )


def _keys(subgraph) -> set[tuple[str, str]]:
    return {(r.method.upper(), r.path) for r in subgraph.impacted_routes}


def test_added_route_is_detected_from_post_edit_state(tmp_path: Path) -> None:
    repo = _write_app(tmp_path, _TWO_ROUTES)
    # Pre-edit graph only knows /existing; the worker added /health.
    graph = RepoGraph(repo_path=str(repo), nodes=[_route_node("GET", "/existing")])

    subgraph = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
        repo_path=repo,
    )

    assert ("GET", "/health") in _keys(subgraph)
    health = next(n for n in subgraph.impacted_nodes if n.name == "GET /health")
    assert health.reason == "route_added_by_diff"


def test_scopes_impacted_routes_to_touched_lines(tmp_path: Path) -> None:
    repo = _write_app(tmp_path, _TWO_ROUTES)
    parsed = PythonParser().parse(repo, "app/main.py")
    health_line = next(r.line for r in parsed.routes if r.path == "/health")
    # Both routes already exist in the graph (neither is "added").
    graph = RepoGraph(
        repo_path=str(repo),
        nodes=[_route_node("GET", "/existing"), _route_node("GET", "/health")],
    )

    subgraph = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
        repo_path=repo,
        changed_line_ranges={"app/main.py": {health_line}},
    )

    keys = _keys(subgraph)
    assert ("GET", "/health") in keys  # touched by the diff
    assert ("GET", "/existing") not in keys  # untouched — no longer over-included


def test_evidence_guard_accepts_worker_added_route(tmp_path: Path) -> None:
    repo = _write_app(tmp_path, _TWO_ROUTES)
    graph = RepoGraph(repo_path=str(repo), nodes=[_route_node("GET", "/existing")])
    subgraph = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
        repo_path=repo,
    )

    report = FinalReport(title="t", markdown="Added a GET /health endpoint with a test.")
    evidence = EvidenceGuard().check(
        report,
        changed_files=["app/main.py"],
        test_results=TestRunSummary(commands=[]),
        changed_subgraph=subgraph,
    )

    route_flags = [
        f for f in evidence.findings if f.claim_type == "route_claim_without_graph_impact"
    ]
    assert route_flags == []


def test_parse_diff_added_ranges_maps_files_to_post_edit_lines() -> None:
    from app.core.graph import _parse_diff_added_ranges

    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -8,0 +9,4 @@\n"
        "+@app.get('/health')\n"
        "+def health():\n"
        "+    return {'status': 'ok'}\n"
        "+\n"
    )
    ranges = _parse_diff_added_ranges(diff)
    assert ranges == {"app/main.py": {9, 10, 11, 12}}


def test_legacy_graph_walk_preserved_without_repo_path(tmp_path: Path) -> None:
    # Without repo_path, behavior is unchanged: routes come from the graph walk.
    graph = RepoGraph(
        repo_path=str(tmp_path),
        nodes=[
            RepoGraphNode(id="file:app/main.py", type="file", name="main.py", path="app/main.py"),
            RepoGraphNode(
                id="function:python:app.main.health", type="function", name="health",
                path="app/main.py",
            ),
            _route_node("GET", "/legacy"),
        ],
    )
    graph.edges = []  # no exposes_route edge → no routes, proving graph-walk path is used
    subgraph = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
    )
    assert subgraph.impacted_routes == []
