from __future__ import annotations

import json

from app.core.repo_graph.models import RepoGraph


def repo_graph_json(graph: RepoGraph) -> str:
    return json.dumps(graph.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
