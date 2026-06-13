from pathlib import Path

from app.core.repo_graph import RepoGraphBuilder
from app.core.repo_graph.impact import ChangedSubgraphBuilder


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_PRE_EDIT = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n\n"
    "@app.get('/old')\n"
    "def old():\n"
    "    return {}\n"
)

_POST_EDIT = _PRE_EDIT + (
    "\n@app.post('/new')\n"
    "def new():\n"
    "    return {}\n"
)


def test_route_added_by_change_is_detected_as_impacted(tmp_path: Path) -> None:
    """A route the worker ADDS in its diff must appear in impacted_routes.

    The repo graph is built from the pre-edit snapshot, so a brand-new route is
    absent from it. The Evidence Guard then false-flags the report's mention of
    that route as ungrounded. The builder must re-parse the changed file's
    current content and pick up routes the diff introduced.
    """
    repo = tmp_path
    main = repo / "app" / "main.py"

    # Pre-edit snapshot: one existing route -> graph knows only /old.
    _write(main, _PRE_EDIT)
    graph = RepoGraphBuilder().build(repo)

    # Worker edit lands on disk: the same file now also exposes POST /new.
    _write(main, _POST_EDIT)

    changed = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
        repo_path=repo,
    )

    routes = {(route.method, route.path) for route in changed.impacted_routes}
    assert ("POST", "/new") in routes  # the newly-added route is recognized
    assert ("GET", "/old") in routes  # and the pre-existing one is still present


def test_added_route_not_duplicated_when_already_in_graph(tmp_path: Path) -> None:
    """Re-parsing must not double-list a route the graph already exposes."""
    repo = tmp_path
    main = repo / "app" / "main.py"
    _write(main, _PRE_EDIT)
    graph = RepoGraphBuilder().build(repo)  # graph already has GET /old

    changed = ChangedSubgraphBuilder().build(
        graph,
        changed_files=["app/main.py"],
        deleted_files=[],
        fallback_validation=[],
        repo_path=repo,
    )

    old_routes = [r for r in changed.impacted_routes if (r.method, r.path) == ("GET", "/old")]
    assert len(old_routes) == 1
