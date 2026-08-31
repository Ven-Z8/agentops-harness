from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.project_control.codegraph import build_codegraph
from app.project_control.handoffs import latest_handoffs
from app.project_control.roadmap import load_roadmap, render_roadmap
from tests.helpers_project_control import seed_control_room

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/project_control.py"
FIXED_TIME = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
UNSAFE_ROADMAP_IDS = [
    "AO/14D",
    r"AO\14D",
    "AO-14D\nforged",
    "AO-14D\x1f",
    "AO-14D\u0085forged",
    "AO-14D\u2028forged",
    "AO-14D\u2029forged",
    ".",
    "..",
]


def run_cli(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _seed_cli_repository(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "CLI tests")
    seed_control_room(root)
    artifacts = root / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    roadmap_output = root / "coordination/roadmap/14-day-plan.md"
    roadmap_output.write_text(render_roadmap(load_roadmap(root)), encoding="utf-8")
    (root / "app/project_control").mkdir(parents=True)
    (root / "app/project_control/fixture.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture inputs")
    build_codegraph(root, FIXED_TIME)
    _git(root, "add", "coordination/codegraph")
    _git(root, "commit", "-qm", "fixture graph")


def test_validate_command_succeeds_on_committed_control_room() -> None:
    result = run_cli("validate")

    assert result.returncode == 0, result.stderr
    assert "control room valid" in result.stdout.lower()


def test_cli_help_lists_all_local_commands() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    commands = ("validate", "snapshot", "codegraph", "handoff")
    assert all(command in result.stdout for command in commands)


def test_validate_reports_every_invalid_path_without_traceback(tmp_path: Path) -> None:
    _seed_cli_repository(tmp_path)
    (tmp_path / "coordination/roadmap/14-day-plan.md").write_text("stale\n", encoding="utf-8")
    (tmp_path / "coordination/artifacts/index.yaml").write_text("invalid: true\n", encoding="utf-8")

    result = run_cli("validate", cwd=tmp_path)

    assert result.returncode == 2
    assert "coordination/roadmap/14-day-plan.md" in result.stderr
    assert "coordination/artifacts/index.yaml" in result.stderr
    assert "Traceback" not in result.stderr


def test_malformed_project_yaml_is_invalid_for_validate_and_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "coordination/project.yaml"
    project.parent.mkdir(parents=True)
    project.write_text("schema_version: [unterminated\n", encoding="utf-8")

    for command in ("validate", "snapshot"):
        result = run_cli(command, cwd=tmp_path)

        assert result.returncode == 2
        assert "coordination/project.yaml" in result.stderr
        assert "Traceback" not in result.stderr


def test_validate_labels_malformed_roadmap_and_frontmatter_paths(tmp_path: Path) -> None:
    _seed_cli_repository(tmp_path)
    roadmap = tmp_path / "coordination/roadmap/14-day-plan.yaml"
    roadmap.write_text("items: [unterminated\n", encoding="utf-8")
    handoff = tmp_path / "coordination/handoffs/2026-08-30-AO-D01-01-codex.md"
    handoff.parent.mkdir()
    handoff.write_text("---\ntask_id: [unterminated\n---\n", encoding="utf-8")

    result = run_cli("validate", cwd=tmp_path)

    assert result.returncode == 2
    assert "coordination/roadmap/14-day-plan.yaml" in result.stderr
    assert "coordination/handoffs/2026-08-30-AO-D01-01-codex.md" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("target", "path_label"),
    [
        ("project", "coordination/project.yaml"),
        ("roadmap", "coordination/roadmap/14-day-plan.yaml"),
    ],
)
def test_validate_rejects_unsafe_root_roadmap_identifiers_without_traceback(
    tmp_path: Path,
    target: str,
    path_label: str,
) -> None:
    _seed_cli_repository(tmp_path)
    project_path = tmp_path / "coordination/project.yaml"
    roadmap_path = tmp_path / "coordination/roadmap/14-day-plan.yaml"
    project_payload = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    roadmap_payload = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))

    for invalid_identifier in UNSAFE_ROADMAP_IDS:
        candidate = dict(project_payload if target == "project" else roadmap_payload)
        if target == "project":
            candidate["roadmap"] = dict(project_payload["roadmap"])
            candidate["roadmap"]["id"] = invalid_identifier
            project_path.write_text(
                yaml.safe_dump(candidate, allow_unicode=True),
                encoding="utf-8",
            )
        else:
            candidate["roadmap_id"] = invalid_identifier
            roadmap_path.write_text(
                yaml.safe_dump(candidate, allow_unicode=True),
                encoding="utf-8",
            )

        result = run_cli("validate", cwd=tmp_path)

        assert result.returncode == 2
        assert path_label in result.stderr
        assert "Traceback" not in result.stderr


def test_validate_preserves_project_and_roadmap_id_consistency_check(tmp_path: Path) -> None:
    _seed_cli_repository(tmp_path)
    project_path = tmp_path / "coordination/project.yaml"
    payload = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    payload["roadmap"]["id"] = "AO-OTHER"
    project_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = run_cli("validate", cwd=tmp_path)

    assert result.returncode == 2
    assert "Roadmap ID does not match project configuration" in result.stderr
    assert "Traceback" not in result.stderr


def test_local_generation_and_handoff_commands_use_repository_state(tmp_path: Path) -> None:
    _seed_cli_repository(tmp_path)

    codegraph = run_cli("codegraph", cwd=tmp_path)
    snapshot = run_cli("snapshot", cwd=tmp_path)
    handoff = run_cli("handoff", "--task", "AO-D01-01", "--harness", "codex", cwd=tmp_path)

    assert codegraph.returncode == 0, codegraph.stderr
    assert snapshot.returncode == 0, snapshot.stderr
    assert handoff.returncode == 0, handoff.stderr
    assert "Fresh: the manifest source-tree digest matches tracked inputs." in (
        tmp_path / "coordination/CURRENT.md"
    ).read_text(encoding="utf-8")
    assert "Planned after Task 6" not in (
        tmp_path / "coordination/CURRENT.md"
    ).read_text(encoding="utf-8")
    handoff_path = next((tmp_path / "coordination/handoffs").glob("*-AO-D01-01-codex.md"))
    header = yaml.safe_load(handoff_path.read_text(encoding="utf-8").split("---")[1])
    assert header["branch"] == "main"
    assert header["base_commit"] == _git(tmp_path, "rev-parse", "HEAD")
    assert header["head_commit"] == _git(tmp_path, "rev-parse", "HEAD")
    assert latest_handoffs(tmp_path)["AO-D01-01"] == handoff_path


def test_handoff_rejects_unsafe_identifiers_without_traceback(tmp_path: Path) -> None:
    _seed_cli_repository(tmp_path)

    for option, value in (("--task", "../AO-D01-01"), ("--harness", "bad\\slug")):
        arguments = ["handoff", "--task", "AO-D01-01", "--harness", "codex"]
        arguments[arguments.index(option) + 1] = value
        result = run_cli(*arguments, cwd=tmp_path)

        assert result.returncode == 2
        assert "Traceback" not in result.stderr


def test_expected_failures_map_to_stable_exit_codes_without_tracebacks(
    monkeypatch,
    capsys,
) -> None:
    from app.project_control import cli
    from app.project_control.errors import (
        DependencyUnavailable,
        InvalidControlRoom,
        RemotePartialFailure,
    )

    cases = [
        (InvalidControlRoom("bad state"), 2, "control room invalid"),
        (DependencyUnavailable("missing tool"), 3, "dependency unavailable"),
        (RemotePartialFailure("unfinished"), 4, "remote reconciliation incomplete"),
    ]
    for error, expected_code, expected_message in cases:
        def fail(_args, *, raised=error):
            raise raised

        monkeypatch.setattr(cli, "_validate_command", fail)
        assert cli.main(["validate"]) == expected_code
        captured = capsys.readouterr()
        assert expected_message in captured.err
        assert "Traceback" not in captured.err


def test_usage_errors_return_two_without_traceback() -> None:
    result = run_cli("unknown-command")

    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_root_agents_file_links_control_room_in_one_hop() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "coordination/README.md" in text
    assert "project_control.py validate" in text
    assert text.count("### Before work") == 1
    assert text.count("### During work") == 1
    assert text.count("### At handoff") == 1


def test_coordination_index_links_every_authoritative_surface() -> None:
    text = (REPO_ROOT / "coordination/README.md").read_text(encoding="utf-8")

    for target in (
        "PROJECT.md",
        "CURRENT.md",
        "roadmap/14-day-plan.md",
        "BOARD.md",
        "decisions/README.md",
        "handoffs/README.md",
        "artifacts/README.md",
        "codegraph/summary.md",
        "templates/",
        "designs/2026-08-30-project-control-room-design.md",
        "plans/2026-08-30-project-control-room-implementation.md",
    ):
        assert target in text


def test_project_boundary_preserves_vlm_vla_limitations() -> None:
    text = (REPO_ROOT / "coordination/PROJECT.md").read_text(encoding="utf-8")

    assert "coordination and governance system" in text
    assert "does not implement" in text
    assert "VLM" in text
    assert "VLA" in text
