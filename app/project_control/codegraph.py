"""Deterministic, tracked-source repository graph exports for the control room."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from app.core.repo_graph import RepoGraph, RepoGraphBuilder
from app.core.repo_graph.serializer import repo_graph_json
from app.project_control.io import atomic_write, load_yaml, resolve_inside
from app.project_control.models import GeneratedPaths, GraphManifest, ProjectConfig

GENERATOR_VERSION = "1"
_CODEGRAPH_DIRECTORY = Path("coordination/codegraph")
_DEFAULT_GENERATED_PATHS = GeneratedPaths(
    board="coordination/BOARD.md",
    current="coordination/CURRENT.md",
    codegraph=_CODEGRAPH_DIRECTORY.as_posix(),
)
_SEMANTIC_LANGUAGES = {"java", "python"}
_FILE_ONLY_SUFFIXES = {
    ".cjs": "javascript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".mts": "typescript",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_EXCLUDED_PARTS = RepoGraphBuilder.IGNORED_PARTS | {".cache", ".next", "coverage", "vendor"}


def _generated_paths(root: Path, config: ProjectConfig | None) -> GeneratedPaths:
    if config is not None:
        return config.generated
    project_path = root / "coordination/project.yaml"
    if project_path.exists() or project_path.is_symlink():
        return load_yaml(project_path, ProjectConfig, root=root).generated
    return _DEFAULT_GENERATED_PATHS


def _exclusions(generated: GeneratedPaths) -> list[str]:
    return sorted(
        [
            generated.board,
            generated.current,
            f"{generated.codegraph.rstrip('/')}/",
            "coordination/artifacts/",
            *[f"{part}/" for part in _EXCLUDED_PARTS | {".git"}],
        ]
    )


def file_only_language(relative_path: str) -> str | None:
    """Return file-level-only coverage for JavaScript and TypeScript inputs."""
    return _FILE_ONLY_SUFFIXES.get(Path(relative_path).suffix.lower())


def _validated_relative_file(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"Path must remain inside repository: {relative}")
    resolved = resolve_inside(relative, root)
    if not resolved.is_file():
        raise ValueError(f"Graph input must be a regular file: {relative}")
    return Path(*relative.parts)


def _is_excluded(relative: Path, generated: GeneratedPaths) -> bool:
    parts = relative.parts
    codegraph = Path(generated.codegraph)
    return (
        relative.as_posix() in {generated.board, generated.current}
        or parts[:2] == ("coordination", "artifacts")
        or parts[: len(codegraph.parts)] == codegraph.parts
        or bool(set(parts).intersection(_EXCLUDED_PARTS))
    )


def tracked_graph_inputs(root: Path, *, config: ProjectConfig | None = None) -> list[Path]:
    """List validated, tracked source files while excluding generated and cache paths."""
    root = root.resolve(strict=True)
    generated = _generated_paths(root, config)
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    paths: list[Path] = []
    for value in result.stdout.split(b"\0"):
        if not value:
            continue
        relative = Path(value.decode("utf-8"))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError(f"Path must remain inside repository: {relative}")
        if _is_excluded(relative, generated):
            continue
        validated = _validated_relative_file(root, relative)
        paths.append(validated)
    return sorted(paths, key=lambda value: value.as_posix())


def source_tree_digest(root: Path, paths: list[Path]) -> str:
    """Hash normalized names and raw bytes of the validated source-tree inputs."""
    root = root.resolve(strict=True)
    digest = hashlib.sha256()
    for relative in sorted(paths, key=lambda value: value.as_posix()):
        validated = _validated_relative_file(root, relative)
        digest.update(validated.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / validated).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_tracked_inputs(root: Path, isolated: Path, paths: list[Path]) -> None:
    for relative in paths:
        validated = _validated_relative_file(root, relative)
        destination = isolated / validated
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(root / validated, destination)


def _is_file_only_test(path: str) -> bool:
    relative = Path(path)
    name = relative.name.lower()
    return (
        "tests" in relative.parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _annotate_file_only_languages(graph: RepoGraph) -> None:
    file_only_paths: set[str] = set()
    for node in graph.nodes:
        if node.type not in {"file", "test"} or node.path is None:
            continue
        language = file_only_language(node.path)
        if language is None:
            continue
        node.language = language
        if node.type == "file" and _is_file_only_test(node.path):
            node.type = "test"
        file_only_paths.add(node.path)

    graph.summary.languages = sorted(set(graph.summary.languages) | {
        file_only_language(path) for path in file_only_paths if file_only_language(path) is not None
    })
    graph.summary.source_file_count += len(file_only_paths)
    graph.summary.test_file_count = sum(node.type == "test" for node in graph.nodes)


def build_export_graph(root: Path, paths: list[Path]) -> RepoGraph:
    """Build the graph from an isolated copy of validated, tracked source inputs."""
    root = root.resolve(strict=True)
    validated_paths = [_validated_relative_file(root, path) for path in paths]
    with TemporaryDirectory(prefix="agentops-codegraph-") as directory:
        isolated = Path(directory)
        _copy_tracked_inputs(root, isolated, validated_paths)
        graph = RepoGraphBuilder().build(isolated).model_copy(deep=True)
    graph.repo_path = "."
    _annotate_file_only_languages(graph)
    return graph


def _source_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _language_coverage(graph: RepoGraph) -> dict[str, list[str]]:
    observed = set(graph.summary.languages)
    file_only = sorted(observed & set(_FILE_ONLY_SUFFIXES.values()))
    semantic = sorted(observed & _SEMANTIC_LANGUAGES)
    unsupported = sorted(
        {
            Path(node.path).suffix.lower()
            for node in graph.nodes
            if node.type in {"file", "test", "config"}
            and node.path
            and node.language is None
            and Path(node.path).suffix
        }
    )
    return {"semantic": semantic, "file-only": file_only, "unsupported": unsupported}


def _graph_counts(graph: RepoGraph, paths: list[Path]) -> dict[str, int]:
    return {
        "edges": len(graph.edges),
        "included_files": len(paths),
        "nodes": len(graph.nodes),
        "source_files": graph.summary.source_file_count,
        "test_files": graph.summary.test_file_count,
    }


def _summary(markdown_manifest: GraphManifest, graph: RepoGraph) -> str:
    coverage = markdown_manifest.language_coverage
    lines = [
        "# Repository code graph",
        "",
        f"- Generated at: {_timestamp(markdown_manifest.generated_at)}",
        f"- Source commit: `{markdown_manifest.source_commit}`",
        f"- Source tree digest: `{markdown_manifest.source_tree_digest}`",
        f"- Included files: {markdown_manifest.counts['included_files']}",
        f"- Nodes: {markdown_manifest.counts['nodes']}",
        f"- Edges: {markdown_manifest.counts['edges']}",
        "",
        "## Language coverage",
        "",
        f"- Semantic: {', '.join(coverage['semantic']) or 'none'}",
        f"- File-only: {', '.join(coverage['file-only']) or 'none'}",
        f"- Unsupported: {', '.join(coverage['unsupported']) or 'none'}",
        "",
        "JavaScript and TypeScript receive file-level coverage only; this export does not parse "
        "their symbols.",
        "",
        "## Graph summary",
        "",
        f"- Source files: {graph.summary.source_file_count}",
        f"- Test files: {graph.summary.test_file_count}",
        f"- Dependencies: {graph.summary.dependency_count}",
        f"- Migration risks: {graph.summary.risk_count}",
        "",
    ]
    return "\n".join(lines)


def build_codegraph(
    root: Path, now: datetime, *, config: ProjectConfig | None = None
) -> GraphManifest:
    """Write deterministic codegraph artifacts and return their strict manifest."""
    root = root.resolve(strict=True)
    generated = _generated_paths(root, config)
    paths = tracked_graph_inputs(root, config=config)
    graph = build_export_graph(root, paths)
    manifest = GraphManifest(
        schema_version=1,
        generator_version=GENERATOR_VERSION,
        source_commit=_source_commit(root),
        source_tree_digest=source_tree_digest(root, paths),
        included_paths=[path.as_posix() for path in paths],
        exclusions=_exclusions(generated),
        counts=_graph_counts(graph, paths),
        generated_at=_timestamp(now),
        language_coverage=_language_coverage(graph),
    )
    destination = root / generated.codegraph
    atomic_write(destination / "graph.json", repo_graph_json(graph), root=root)
    atomic_write(destination / "summary.md", _summary(manifest, graph), root=root)
    atomic_write(
        destination / "manifest.json",
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        root=root,
    )
    return manifest


def validate_codegraph_freshness(root: Path, *, config: ProjectConfig | None = None) -> None:
    """Raise when the graph export no longer matches the current tracked source tree."""
    root = root.resolve(strict=True)
    generated = _generated_paths(root, config)
    manifest_path = resolve_inside(root / generated.codegraph / "manifest.json", root)
    manifest = GraphManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    current_digest = source_tree_digest(root, tracked_graph_inputs(root, config=config))
    if current_digest != manifest.source_tree_digest:
        raise ValueError("Codegraph is stale: source-tree digest differs from manifest")
