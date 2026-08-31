"""Local command-line workflow for the Project Control Room."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.project_control.artifacts import load_artifact_index
from app.project_control.codegraph import build_codegraph, validate_codegraph_freshness
from app.project_control.decisions import load_recent_decisions
from app.project_control.errors import (
    DependencyUnavailable,
    InvalidControlRoom,
    RemotePartialFailure,
)
from app.project_control.github import GitHubClient, SubprocessGhTransport
from app.project_control.handoffs import create_handoff, load_latest_handoffs
from app.project_control.io import load_frontmatter, load_yaml, resolve_inside
from app.project_control.models import DecisionHeader, HandoffHeader, ProjectConfig
from app.project_control.roadmap import load_roadmap, render_roadmap
from app.project_control.snapshots import write_initial_snapshots, write_snapshots


def _repository_root() -> Path:
    return Path.cwd().resolve(strict=True)


def _relative_label(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _record_issue(
    issues: list[str],
    label: str,
    operation: Callable[[], Any],
) -> Any | None:
    try:
        return operation()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        issues.append(f"{label}: {error}")
        return None


def _validate_frontmatter_records(
    root: Path,
    directory: Path,
    model_type: type[HandoffHeader] | type[DecisionHeader],
    issues: list[str],
) -> bool:
    if not directory.exists():
        return True
    try:
        resolved = resolve_inside(directory, root)
    except ValueError as error:
        issues.append(f"{_relative_label(root, directory)}: {error}")
        return False
    valid = True
    for path in sorted(resolved.glob("*.md")):
        if path.name == "README.md":
            continue
        label = _relative_label(root, path)
        if (
            _record_issue(
                issues,
                label,
                lambda path=path: load_frontmatter(path, model_type, root=root),
            )
            is None
        ):
            valid = False
    return valid


def validate_control_room(root: Path) -> None:
    """Validate all local authorities and generated roadmap/graph derivatives."""
    root = root.resolve(strict=True)
    issues: list[str] = []
    project_path = root / "coordination/project.yaml"
    project = _record_issue(
        issues,
        "coordination/project.yaml",
        lambda: load_yaml(project_path, ProjectConfig, root=root),
    )
    if not isinstance(project, ProjectConfig):
        raise InvalidControlRoom("\n".join(issues))

    roadmap = _record_issue(
        issues,
        project.roadmap.source,
        lambda: load_roadmap(root),
    )
    _record_issue(
        issues,
        "coordination/artifacts/index.yaml",
        lambda: load_artifact_index(root),
    )

    handoffs_dir = root / "coordination/handoffs"
    if _validate_frontmatter_records(root, handoffs_dir, HandoffHeader, issues):
        _record_issue(issues, "coordination/handoffs", lambda: load_latest_handoffs(root))
    decisions_dir = root / "coordination/decisions"
    if _validate_frontmatter_records(root, decisions_dir, DecisionHeader, issues):
        _record_issue(issues, "coordination/decisions", lambda: load_recent_decisions(root))

    manifest_label = f"{project.generated.codegraph}/manifest.json"
    _record_issue(
        issues,
        manifest_label,
        lambda: validate_codegraph_freshness(root, config=project),
    )

    if roadmap is not None:
        rendered_path = Path(project.roadmap.source).with_suffix(".md")

        def compare_roadmap() -> None:
            resolved = resolve_inside(root / rendered_path, root)
            committed = resolved.read_text(encoding="utf-8")
            expected = render_roadmap(roadmap)
            if committed != expected:
                raise ValueError("generated roadmap content differs from its YAML authority")

        _record_issue(issues, rendered_path.as_posix(), compare_roadmap)

    if issues:
        raise InvalidControlRoom("\n".join(issues))


def _normalize_expected_failure(operation: Callable[[], int]) -> int:
    try:
        return operation()
    except (InvalidControlRoom, DependencyUnavailable, RemotePartialFailure):
        raise
    except FileNotFoundError as error:
        if error.filename == "git":
            raise DependencyUnavailable("required executable 'git' was not found") from error
        raise InvalidControlRoom(str(error)) from error
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise InvalidControlRoom(str(error)) from error


def _validate_command(_args: argparse.Namespace) -> int:
    root = _repository_root()
    validate_control_room(root)
    print("Control room valid.")
    return 0


def _snapshot_command(_args: argparse.Namespace) -> int:
    root = _repository_root()
    write_initial_snapshots(root, datetime.now(UTC))
    print("Repository-only snapshots written.")
    return 0


def _codegraph_command(_args: argparse.Namespace) -> int:
    root = _repository_root()
    project = load_yaml(root / "coordination/project.yaml", ProjectConfig, root=root)
    manifest = build_codegraph(root, datetime.now(UTC), config=project)
    print(
        f"Codegraph written to {project.generated.codegraph} "
        f"({manifest.counts['included_files']} inputs)."
    )
    return 0


def _git_output(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value:
        raise ValueError(f"Git returned no value for: {' '.join(arguments)}")
    return value


def _handoff_command(args: argparse.Namespace) -> int:
    root = _repository_root()
    project = load_yaml(root / "coordination/project.yaml", ProjectConfig, root=root)
    branch = _git_output(root, "branch", "--show-current")
    head_commit = _git_output(root, "rev-parse", "HEAD")
    base_commit = _git_output(
        root,
        "merge-base",
        "HEAD",
        project.project.default_branch,
    )
    path = create_handoff(
        root,
        task_id=args.task,
        harness=args.harness,
        now=datetime.now(UTC),
        branch=branch,
        base_commit=base_commit,
        head_commit=head_commit,
    )
    print(f"Handoff created: {path.relative_to(root).as_posix()}")
    return 0


def _board_export_command(_args: argparse.Namespace) -> int:
    root = _repository_root()
    project = load_yaml(root / "coordination/project.yaml", ProjectConfig, root=root)
    github_project = project.github_project
    if github_project.number is None or github_project.url is None:
        raise InvalidControlRoom("board-export requires a configured GitHub project number and url")
    export = GitHubClient(SubprocessGhTransport()).export_project(
        github_project.owner,
        github_project.number,
        expected_repository=project.project.repository,
    )
    if export.project_url != github_project.url:
        raise InvalidControlRoom(
            "GitHub export project URL does not match coordination/project.yaml"
        )
    if export.repository != project.project.repository:
        raise InvalidControlRoom(
            "GitHub export issue repository does not match coordination/project.yaml"
        )
    write_snapshots(root, export, datetime.now(UTC))
    print(f"Board export written ({len(export.items)} items).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local Project Control Room.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate all local control-room state.")
    validate.set_defaults(handler=_validate_command)

    snapshot = subparsers.add_parser("snapshot", help="Write repository-only snapshots.")
    snapshot.set_defaults(handler=_snapshot_command)

    codegraph = subparsers.add_parser("codegraph", help="Regenerate configured graph outputs.")
    codegraph.set_defaults(handler=_codegraph_command)

    handoff = subparsers.add_parser("handoff", help="Create a structured task handoff.")
    handoff.add_argument("--task", required=True, help="Stable roadmap task ID.")
    handoff.add_argument("--harness", required=True, help="Lowercase harness slug.")
    handoff.set_defaults(handler=_handoff_command)

    board_export = subparsers.add_parser(
        "board-export", help="Export the configured GitHub Project read-only."
    )
    board_export.set_defaults(handler=_board_export_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _normalize_expected_failure(lambda: args.handler(args))
    except InvalidControlRoom as exc:
        print(f"control room invalid: {exc}", file=sys.stderr)
        return 2
    except DependencyUnavailable as exc:
        print(f"dependency unavailable: {exc}", file=sys.stderr)
        return 3
    except RemotePartialFailure as exc:
        print(f"remote reconciliation incomplete: {exc}", file=sys.stderr)
        return 4
