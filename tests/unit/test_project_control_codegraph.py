from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.project_control.codegraph import (
    build_codegraph,
    build_export_graph,
    source_tree_digest,
    tracked_graph_inputs,
    validate_codegraph_freshness,
)
from app.project_control.models import ProjectConfig
from tests.helpers_project_control import valid_project_config

FIXED_TIME = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _tracked_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Codegraph tests")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial inputs")
    return root


def test_control_room_graph_marks_typescript_as_file_only(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    (root / "web").mkdir(parents=True)
    (root / "web/app.tsx").write_text("export const App = () => <main />;\n", encoding="utf-8")

    graph = build_export_graph(root, [Path("web/app.tsx")])

    assert graph.repo_path == "."
    assert "typescript" in graph.summary.languages
    assert any(node.path == "web/app.tsx" and node.language == "typescript" for node in graph.nodes)
    assert not any(node.type in {"function", "class", "method"} for node in graph.nodes)


def test_control_room_graph_marks_javascript_test_files_without_symbol_parsing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "inputs"
    (root / "web").mkdir(parents=True)
    (root / "web/app.test.js").write_text("test('app', () => {});\n", encoding="utf-8")

    graph = build_export_graph(root, [Path("web/app.test.js")])

    assert "javascript" in graph.summary.languages
    assert any(
        node.path == "web/app.test.js" and node.language == "javascript" and node.type == "test"
        for node in graph.nodes
    )
    assert not any(node.type in {"function", "class", "method"} for node in graph.nodes)


def test_tracked_graph_inputs_exclude_dirty_untracked_and_generated_paths(tmp_path: Path) -> None:
    root = _tracked_repo(
        tmp_path,
        {
            "app/kept.py": "VALUE = 1\n",
            "coordination/codegraph/graph.json": "{}\n",
            "vendor/ignored.py": "VALUE = 2\n",
        },
    )
    (root / "app/kept.py").write_text("VALUE = 9\n", encoding="utf-8")
    (root / "app/untracked.py").write_text("VALUE = 3\n", encoding="utf-8")

    paths = tracked_graph_inputs(root)

    assert [path.as_posix() for path in paths] == ["app/kept.py"]


def test_tracked_graph_inputs_exclude_macos_finder_metadata(tmp_path: Path) -> None:
    """A tracked .DS_Store must not enter digest inputs.

    macOS Finder rewrites .DS_Store non-deterministically (window geometry,
    icon positions). A manifest computed locally can therefore be stale by
    the time the commit lands, failing CI on every push from a mac. The
    file is Finder state, not source.
    """
    root = _tracked_repo(
        tmp_path,
        {
            "app/kept.py": "VALUE = 1\n",
            ".DS_Store": "\x00\x00\x01finder-junk\x00",
        },
    )

    paths = tracked_graph_inputs(root)

    assert [path.as_posix() for path in paths] == ["app/kept.py"]


def test_tracked_graph_inputs_include_staged_file(tmp_path: Path) -> None:
    root = _tracked_repo(tmp_path, {"app/kept.py": "VALUE = 1\n"})
    staged = root / "app/staged.py"
    staged.write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", staged.relative_to(root).as_posix())

    assert [path.as_posix() for path in tracked_graph_inputs(root)] == [
        "app/kept.py",
        "app/staged.py",
    ]


def test_source_digest_changes_when_a_tracked_file_changes(tmp_path: Path) -> None:
    root = _tracked_repo(tmp_path, {"app/kept.py": "VALUE = 1\n"})
    paths = tracked_graph_inputs(root)
    first = source_tree_digest(root, paths)
    (root / "app/kept.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert source_tree_digest(root, tracked_graph_inputs(root)) != first


def test_source_digest_ignores_generated_graph_files(tmp_path: Path) -> None:
    root = _tracked_repo(
        tmp_path,
        {"app/kept.py": "VALUE = 1\n", "coordination/codegraph/summary.md": "first\n"},
    )
    paths = tracked_graph_inputs(root)
    first = source_tree_digest(root, paths)
    (root / "coordination/codegraph/summary.md").write_text("changed\n", encoding="utf-8")

    assert not any(path.as_posix().startswith("coordination/codegraph/") for path in paths)
    assert source_tree_digest(root, tracked_graph_inputs(root)) == first


def test_source_digest_ignores_coordination_evidence_but_tracks_source_changes(
    tmp_path: Path,
) -> None:
    root = _tracked_repo(
        tmp_path,
        {
            "app/kept.py": "VALUE = 1\n",
            "coordination/artifacts/index.yaml": "schema_version: 1\nartifacts: []\n",
            "coordination/artifacts/report.yaml": "result: initial\n",
        },
    )
    paths = tracked_graph_inputs(root)
    first = source_tree_digest(root, paths)
    assert not any(path.as_posix().startswith("coordination/artifacts/") for path in paths)
    (root / "coordination/artifacts/report.yaml").write_text("result: changed\n", encoding="utf-8")
    assert source_tree_digest(root, tracked_graph_inputs(root)) == first
    (root / "app/kept.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert source_tree_digest(root, tracked_graph_inputs(root)) != first


def test_graph_manifest_discloses_evidence_exclusion(tmp_path: Path) -> None:
    root = _tracked_repo(tmp_path, {"app/kept.py": "VALUE = 1\n"})
    manifest = build_codegraph(root, FIXED_TIME)
    assert "coordination/artifacts/" in manifest.exclusions


def test_configured_generated_outputs_are_excluded_before_file_validation(
    tmp_path: Path,
) -> None:
    """A deleted configured output must not fail before graph exclusions are applied."""
    root = _tracked_repo(
        tmp_path,
        {
            "app/kept.py": "VALUE = 1\n",
            "coordination/CURRENT.md": "current\n",
            "coordination/BOARD.md": "board\n",
            "coordination/generated/graph/manifest.json": "{}\n",
        },
    )
    payload = valid_project_config()
    payload["generated"] = {
        "current": "coordination/CURRENT.md",
        "board": "coordination/BOARD.md",
        "codegraph": "coordination/generated/graph",
    }
    config = ProjectConfig.model_validate(payload)
    (root / "coordination/CURRENT.md").unlink()
    (root / "coordination/BOARD.md").write_text("dirty board\n", encoding="utf-8")

    paths = tracked_graph_inputs(root, config=config)

    assert [path.as_posix() for path in paths] == ["app/kept.py"]


def test_codegraph_build_and_freshness_use_configured_directory(tmp_path: Path) -> None:
    """Hard-coding the default directory would validate a different manifest than was built."""
    root = _tracked_repo(tmp_path, {"app/service.py": "VALUE = 1\n"})
    payload = valid_project_config()
    payload["generated"]["codegraph"] = "coordination/generated/graph"
    config = ProjectConfig.model_validate(payload)

    manifest = build_codegraph(root, FIXED_TIME, config=config)

    assert (root / "coordination/generated/graph/manifest.json").is_file()
    assert not (root / "coordination/codegraph/manifest.json").exists()
    assert manifest.included_paths == ["app/service.py"]
    validate_codegraph_freshness(root, config=config)


@pytest.mark.parametrize("relative", [Path("linked.py"), Path("nested/linked.py")])
def test_control_room_graph_rejects_symlink_input(tmp_path: Path, relative: Path) -> None:
    root = tmp_path / "inputs"
    root.mkdir()
    target = root / "target.py"
    target.write_text("SECRET = 'not graph input'\n", encoding="utf-8")
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        build_export_graph(root, [relative])


@pytest.mark.parametrize("relative", [Path("../outside.py"), Path("nested/../../outside.py")])
def test_control_room_graph_rejects_traversal_input(tmp_path: Path, relative: Path) -> None:
    root = tmp_path / "inputs"
    root.mkdir()

    with pytest.raises(ValueError, match="inside repository"):
        build_export_graph(root, [relative])


def test_control_room_graph_rejects_directory_input(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    (root / "directory").mkdir(parents=True)

    with pytest.raises(ValueError, match="regular file"):
        build_export_graph(root, [Path("directory")])


def test_codegraph_generator_is_stable_for_fixed_time_and_fresh_until_sources_change(
    tmp_path: Path,
) -> None:
    root = _tracked_repo(
        tmp_path,
        {"app/service.py": "def answer() -> int:\n    return 42\n"},
    )

    manifest = build_codegraph(root, FIXED_TIME)
    first_outputs = {
        path.name: path.read_bytes()
        for path in sorted((root / "coordination/codegraph").iterdir())
    }
    second_manifest = build_codegraph(root, FIXED_TIME)
    second_outputs = {
        path.name: path.read_bytes()
        for path in sorted((root / "coordination/codegraph").iterdir())
    }

    assert manifest == second_manifest
    assert first_outputs == second_outputs
    assert manifest.source_commit == _git_output(root, "rev-parse", "HEAD")
    assert manifest.generated_at == FIXED_TIME
    validate_codegraph_freshness(root)

    (root / "app/service.py").write_text("def answer() -> int:\n    return 43\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        validate_codegraph_freshness(root)
