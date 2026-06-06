from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RepoNodeType = Literal[
    "folder",
    "file",
    "module",
    "class",
    "function",
    "method",
    "dependency",
    "import",
    "route",
    "config",
    "test",
    "migration_risk",
]

RepoEdgeType = Literal[
    "contains",
    "defines",
    "imports",
    "declares_dependency",
    "exposes_route",
    "tests",
    "likely_tests",
    "depends_on",
    "has_risk",
    "affects",
]


class RepoGraphNode(BaseModel):
    id: str
    type: RepoNodeType
    name: str
    path: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoGraphEdge(BaseModel):
    source: str
    target: str
    type: RepoEdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoGraphSummary(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    build_tools: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    source_file_count: int = 0
    test_file_count: int = 0
    dependency_count: int = 0
    risk_count: int = 0


class RepoGraph(BaseModel):
    repo_path: str
    summary: RepoGraphSummary = Field(default_factory=RepoGraphSummary)
    nodes: list[RepoGraphNode] = Field(default_factory=list)
    edges: list[RepoGraphEdge] = Field(default_factory=list)
