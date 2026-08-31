from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.project_control.snapshots as snapshots
from app.project_control.codegraph import build_codegraph
from app.project_control.errors import InvalidControlRoom
from app.project_control.models import BoardExport
from app.project_control.snapshots import (
    _snapshot_source_revision,
    render_board,
    render_current,
    write_initial_snapshots,
    write_snapshots,
)
from tests.helpers_project_control import make_control_room_state, seed_control_room

FIXED_TIME = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def test_board_snapshot_declares_live_authority() -> None:
    """Removing the generated/authority banner would make offline state misleading."""
    export = BoardExport(project_url="https://github.com/users/Ven-Z8/projects/1", items=[])

    rendered = render_board(export, datetime(2026, 8, 30, 17, tzinfo=UTC))

    assert "Generated snapshot; do not edit manually" in rendered
    assert "GitHub Issues and Projects are authoritative for live execution state" in rendered


def test_board_snapshot_sorts_live_work_by_execution_priority() -> None:
    """Changing the declared sort key would put less urgent live work first."""
    export = BoardExport.model_validate(
        {
            "project_url": "https://github.com/users/Ven-Z8/projects/1",
            "source_revision": "a" * 40,
            "items": [
                {
                    "task_id": "AO-D02-01",
                    "title": "Ready P0",
                    "status": "ready",
                    "priority": "P0",
                    "day": 2,
                },
                {
                    "task_id": "AO-D01-02",
                    "title": "Blocked P3",
                    "status": "blocked",
                    "priority": "P3",
                    "day": 1,
                },
                {
                    "task_id": "AO-D01-01",
                    "title": "Blocked P0",
                    "status": "blocked",
                    "priority": "P0",
                    "day": 1,
                },
            ],
        }
    )

    rendered = render_board(export, FIXED_TIME)

    assert rendered.index("AO-D01-01") < rendered.index("AO-D01-02") < rendered.index("AO-D02-01")


def test_current_snapshot_exposes_required_onboarding_context() -> None:
    """Dropping current-state sections would leave a new agent without required context."""
    rendered = render_current(make_control_room_state(), FIXED_TIME)

    assert "## Current phase" in rendered
    assert "## Immediate objective" in rendered
    assert "## Confirmed baseline" in rendered
    assert "Baseline commit:" in rendered
    assert "## Active blockers" in rendered
    assert "## Latest decisions and handoffs" in rendered
    assert "## Code graph freshness" in rendered
    assert "Snapshot input revision:" in rendered
    assert "Generated snapshot outputs are excluded" in rendered
    assert "uv run python scripts/project_control.py validate" in rendered


def test_invalid_export_does_not_replace_last_good_board(tmp_path: Path) -> None:
    """Skipping validation before write would destroy the last usable board snapshot."""
    board = tmp_path / "coordination/BOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text("last good\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        write_snapshots(tmp_path, {"invalid": True}, FIXED_TIME)

    assert board.read_text(encoding="utf-8") == "last good\n"


def test_initial_snapshots_are_stable_and_identify_unprovisioned_project(tmp_path: Path) -> None:
    """A clock-dependent or live-state claim would make repository snapshots non-repeatable."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")

    write_initial_snapshots(tmp_path, FIXED_TIME)
    first = {
        name: (tmp_path / "coordination" / name).read_bytes() for name in ("CURRENT.md", "BOARD.md")
    }
    write_initial_snapshots(tmp_path, FIXED_TIME)
    second = {
        name: (tmp_path / "coordination" / name).read_bytes() for name in ("CURRENT.md", "BOARD.md")
    }

    assert first == second
    assert b"GitHub project: not provisioned" in first["BOARD.md"]
    assert b"AO-D01-01" in first["BOARD.md"]
    assert b"## Blocked work" in first["BOARD.md"]
    assert b"## Harness assignments" in first["BOARD.md"]


def test_live_board_export_controls_current_phase_objective_and_blockers() -> None:
    """Using roadmap state despite a live export would present stale operational status."""
    state = make_control_room_state().model_copy(
        update={
            "board_export": BoardExport.model_validate(
                {
                    "project_url": "https://github.com/users/Ven-Z8/projects/1",
                    "source_revision": "b" * 40,
                    "items": [
                        {
                            "task_id": "AO-D09",
                            "title": "Live blocked objective",
                            "status": "blocked",
                            "priority": "P0",
                            "day": 9,
                            "phase_id": "AO-P4",
                            "blocker": "waiting for a live approval",
                        }
                    ],
                }
            )
        }
    )

    rendered = render_current(state, FIXED_TIME)

    assert "AO-P4 (live board)" in rendered
    assert "AO-D09: Live blocked objective" in rendered
    assert "AO-D09: waiting for a live approval" in rendered
    assert "AO-P1: Trust and Benchmark Integrity" not in rendered


def test_snapshot_writer_preserves_both_files_when_second_destination_is_a_symlink(
    tmp_path: Path,
) -> None:
    """Replacing CURRENT.md before rejecting BOARD.md would create a preventable partial update."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    current = tmp_path / "coordination/CURRENT.md"
    board = tmp_path / "coordination/BOARD.md"
    outside = tmp_path.parent / "outside-board.md"
    current.write_text("last current\n", encoding="utf-8")
    outside.write_text("last board\n", encoding="utf-8")
    board.symlink_to(outside)

    with pytest.raises(ValueError, match="without symlink"):
        write_initial_snapshots(tmp_path, FIXED_TIME)

    assert current.read_text(encoding="utf-8") == "last current\n"
    assert outside.read_text(encoding="utf-8") == "last board\n"


def test_current_and_initial_board_render_repository_record_links(tmp_path: Path) -> None:
    """Dropping record paths would make latest decisions and handoffs impossible to inspect."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    handoffs = tmp_path / "coordination/handoffs"
    handoffs.mkdir()
    handoffs.joinpath("2026-08-30-AO-D01-01-codex.md").write_text(
        "---\n"
        "schema_version: 1\ntask_id: AO-D01-01\nharness: codex\nstatus: partial\n"
        "started_at: 2026-08-30T15:00:00Z\nupdated_at: 2026-08-30T16:00:00Z\n"
        "branch: codex/AO-D01-01\nbase_commit: '1"
        + "1" * 39
        + "'\nhead_commit: '2"
        + "2" * 39
        + "'\nverification: {state: not_run, commands: []}\nartifacts: []\ndecisions: []\n---\n",
        encoding="utf-8",
    )
    decisions = tmp_path / "coordination/decisions"
    decisions.mkdir()
    decisions.joinpath("ADR-001.md").write_text(
        "---\nschema_version: 1\ndecision_id: ADR-001\nstatus: accepted\n"
        "date: 2026-08-30T17:00:00Z\nowners: [codex]\ntask_ids: [AO-D01-01]\n---\n",
        encoding="utf-8",
    )

    write_initial_snapshots(tmp_path, FIXED_TIME)
    current = (tmp_path / "coordination/CURRENT.md").read_text(encoding="utf-8")
    board = (tmp_path / "coordination/BOARD.md").read_text(encoding="utf-8")

    assert "[Decision ADR-001](<coordination/decisions/ADR-001.md>)" in current
    assert "[Handoff AO-D01-01](<coordination/handoffs/2026-08-30-AO-D01-01-codex.md>)" in current
    assert "[handoff](<coordination/handoffs/2026-08-30-AO-D01-01-codex.md>)" in board


def test_snapshot_record_loading_rejects_unknown_or_malformed_handoffs(tmp_path: Path) -> None:
    """Ignoring malformed or unknown records would turn invalid evidence into an inferred pass."""
    seed_control_room(tmp_path)
    artifacts = tmp_path / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    handoffs = tmp_path / "coordination/handoffs"
    handoffs.mkdir()
    handoffs.joinpath("2026-08-30-AO-UNKNOWN-codex.md").write_text(
        "---\nschema_version: 1\ntask_id: AO-UNKNOWN\n---\n", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        write_initial_snapshots(tmp_path, FIXED_TIME)

    handoffs.joinpath("2026-08-30-AO-UNKNOWN-codex.md").unlink()
    handoffs.joinpath("2026-08-30-AO-D01-01-codex.md").write_text(
        "---\nschema_version: 1\ntask_id: AO-D01-01\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="frontmatter"):
        write_initial_snapshots(tmp_path, FIXED_TIME)


def test_snapshot_provenance_separates_baseline_snapshot_and_graph_revisions() -> None:
    """Using graph provenance as the project baseline would misstate the approved source."""
    state = make_control_room_state().model_copy(update={"snapshot_source_revision": "c" * 40})

    rendered = render_current(state, FIXED_TIME)

    assert "Baseline commit: `39c041f699d7909d1f6853a89bf2a86835a4acd4`" in rendered
    assert "Snapshot input revision: `" + "c" * 40 + "`" in rendered
    assert rendered.count("Graph provenance unavailable; freshness inconclusive.") == 1


@pytest.mark.parametrize("source_revision", ["", "arbitrary", "a" * 39])
def test_board_export_rejects_untruthful_source_revisions(source_revision: str) -> None:
    """Rendering arbitrary text as a revision would create false provenance."""
    with pytest.raises(ValidationError):
        BoardExport.model_validate(
            {
                "project_url": "https://github.com/users/Ven-Z8/projects/1",
                "source_revision": source_revision,
                "items": [],
            }
        )


def test_empty_live_export_remains_authoritative_for_current_state() -> None:
    state = make_control_room_state().model_copy(
        update={
            "board_export": BoardExport(
                project_url="https://github.com/users/Ven-Z8/projects/1", items=[]
            )
        }
    )
    rendered = render_current(state, FIXED_TIME)
    assert "Unassigned (live board)" in rendered
    assert "roadmap fallback" not in rendered


def test_live_rendering_is_deterministic_and_escapes_forged_heading() -> None:
    export = BoardExport.model_validate(
        {
            "project_url": "https://github.com/users/Ven-Z8/projects/1",
            "items": [
                {
                    "task_id": "AO-D01-01",
                    "title": "safe\n## forged",
                    "status": "ready",
                    "priority": "P0",
                }
            ],
        }
    )
    first = render_board(export, FIXED_TIME)
    assert first == render_board(export, FIXED_TIME)
    assert "\n## forged" not in first


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("project_url", "https://github.com/board\n## forged"),
        ("task_id", "AO-D01-01| forged"),
        ("phase_id", "AO-P1\n## forged"),
        ("harness", "codex| forged"),
        ("issue_url", "https://github.com/issues/1>\n## forged"),
        ("handoff", "https://example.test/handoff>\n## forged"),
    ],
)
def test_live_export_rejects_markdown_syntax_in_identifiers_and_links(
    field_name: str, value: str
) -> None:
    """Permitting control text here would let a live export forge Markdown structure."""
    item = {
        "task_id": "AO-D01-01",
        "title": "Safe title",
        "status": "ready",
        "priority": "P0",
    }
    export: dict[str, object] = {
        "project_url": "https://github.com/users/Ven-Z8/projects/1",
        "items": [item],
    }
    if field_name == "project_url":
        export[field_name] = value
    else:
        item[field_name] = value
        if field_name == "issue_url":
            item["issue_number"] = 1

    with pytest.raises(ValidationError):
        BoardExport.model_validate(export)


def test_live_rendering_escapes_display_text_across_all_untrusted_fields() -> None:
    """Removing display escaping would let arbitrary live text forge table cells or links."""
    export = BoardExport.model_validate(
        {
            "project_url": "https://github.com/users/Ven-Z8/projects/1",
            "items": [
                {
                    "task_id": "AO-D01-01",
                    "title": "safe | [forged](https://example.test)\n## heading",
                    "status": "blocked",
                    "priority": "P0",
                    "dependency": "waiting | [forged](https://example.test)\n## heading",
                    "blocker": "blocked | [forged](https://example.test)\n## heading",
                }
            ],
        }
    )

    board = render_board(export, FIXED_TIME)
    current = render_current(
        make_control_room_state().model_copy(update={"board_export": export}), FIXED_TIME
    )

    for rendered in (board, current):
        assert "\n## heading" not in rendered
        assert "[forged](https://example.test)" not in rendered
    assert "safe \\| \\[forged\\]\\(https://example.test\\) \\#\\# heading" in board
    assert "blocked \\| \\[forged\\]\\(https://example.test\\) \\#\\# heading" in current


def test_second_temp_prepare_failure_removes_first_temp_without_replacing_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed second prepare must not leak the first temp or replace either snapshot."""
    current = tmp_path / "coordination/CURRENT.md"
    board = tmp_path / "coordination/BOARD.md"
    current.parent.mkdir(parents=True)
    current.write_text("last current\n", encoding="utf-8")
    board.write_text("last board\n", encoding="utf-8")
    prepared: list[Path] = []
    real_prepare = snapshots._prepare

    def fail_second_prepare(root: Path, path: str, content: str) -> tuple[Path, Path]:
        if prepared:
            raise OSError("second temporary write failed")
        destination, temporary = real_prepare(root, path, content)
        prepared.append(temporary)
        return destination, temporary

    monkeypatch.setattr(snapshots, "_prepare", fail_second_prepare)

    with pytest.raises(OSError, match="second temporary"):
        snapshots._replace_pair(
            tmp_path,
            "coordination/CURRENT.md",
            "new current\n",
            "coordination/BOARD.md",
            "new board\n",
        )

    assert current.read_text(encoding="utf-8") == "last current\n"
    assert board.read_text(encoding="utf-8") == "last board\n"
    assert all(not temporary.exists() for temporary in prepared)


def test_second_replace_failure_restores_both_existing_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "coordination/CURRENT.md"
    board = tmp_path / "coordination/BOARD.md"
    current.parent.mkdir(parents=True)
    current.write_text("old current\n", encoding="utf-8")
    board.write_text("old board\n", encoding="utf-8")
    real_replace = Path.replace
    calls = 0

    def fail_second(source: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(InvalidControlRoom, match="restored"):
        snapshots._replace_pair(
            tmp_path,
            "coordination/CURRENT.md",
            "new current\n",
            "coordination/BOARD.md",
            "new board\n",
        )

    assert current.read_text(encoding="utf-8") == "old current\n"
    assert board.read_text(encoding="utf-8") == "old board\n"


def test_second_replace_failure_keeps_both_initially_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = Path.replace
    calls = 0

    def fail_second(source: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(InvalidControlRoom, match="restored"):
        snapshots._replace_pair(
            tmp_path,
            "coordination/CURRENT.md",
            "new current\n",
            "coordination/BOARD.md",
            "new board\n",
        )

    assert not (tmp_path / "coordination/CURRENT.md").exists()
    assert not (tmp_path / "coordination/BOARD.md").exists()


def test_replace_failure_reports_partial_state_when_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "coordination/CURRENT.md"
    board = tmp_path / "coordination/BOARD.md"
    current.parent.mkdir(parents=True)
    current.write_text("old current\n", encoding="utf-8")
    board.write_text("old board\n", encoding="utf-8")
    real_replace = Path.replace
    real_copyfile = snapshots.shutil.copyfile
    replace_calls = 0
    copy_calls = 0

    def fail_second_replace(source: Path, destination: Path) -> Path:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("injected second replace failure")
        return real_replace(source, destination)

    def fail_restore(source: Path, destination: Path) -> Path:
        nonlocal copy_calls
        copy_calls += 1
        if copy_calls == 3:
            raise OSError("injected rollback failure")
        return real_copyfile(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second_replace)
    monkeypatch.setattr(snapshots.shutil, "copyfile", fail_restore)

    with pytest.raises(InvalidControlRoom, match="rollback was partial"):
        snapshots._replace_pair(
            tmp_path,
            "coordination/CURRENT.md",
            "new current\n",
            "coordination/BOARD.md",
            "new board\n",
        )


@pytest.mark.parametrize(
    ("changed_path", "expect_change"),
    [
        ("coordination/BOARD.md", False),
        ("coordination/CURRENT.md", False),
        ("coordination/project.yaml", True),
        ("app/project_control/snapshots.py", True),
    ],
)
def test_snapshot_source_revision_ignores_outputs_but_tracks_inputs_and_renderer(
    tmp_path: Path, changed_path: str, expect_change: bool
) -> None:
    """Including generated outputs in provenance would make a snapshot invalidate itself."""
    _init_snapshot_git_repository(tmp_path)
    before = _snapshot_source_revision(tmp_path)
    changed = tmp_path / changed_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "add", changed_path)
    _git(tmp_path, "commit", "-m", "change fixture path")

    after = _snapshot_source_revision(tmp_path)

    assert (after != before) is expect_change


def test_snapshot_source_revision_uses_configured_alternate_roadmap(tmp_path: Path) -> None:
    """A hard-coded roadmap path would miss a configured roadmap's committed changes."""
    _init_snapshot_git_repository(tmp_path)
    alternate = tmp_path / "alternate/roadmap.yaml"
    alternate.parent.mkdir()
    alternate.write_bytes((tmp_path / "coordination/roadmap/14-day-plan.yaml").read_bytes())
    project_path = tmp_path / "coordination/project.yaml"
    project_text = project_path.read_text(encoding="utf-8")
    project_path.write_text(
        project_text.replace("coordination/roadmap/14-day-plan.yaml", "alternate/roadmap.yaml"),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "coordination/project.yaml", "alternate/roadmap.yaml")
    _git(tmp_path, "commit", "-m", "configure alternate roadmap")
    before = _snapshot_source_revision(tmp_path)
    alternate.write_text(alternate.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    _git(tmp_path, "add", "alternate/roadmap.yaml")
    _git(tmp_path, "commit", "-m", "change alternate roadmap")

    assert _snapshot_source_revision(tmp_path) != before


@pytest.mark.parametrize(
    "dirty_path",
    [
        "coordination/roadmap/14-day-plan.yaml",
        "app/project_control/snapshots.py",
        "coordination/handoffs/2026-08-30-AO-D01-01-codex.md",
        "coordination/decisions/ADR-001.md",
        "coordination/codegraph/manifest.json",
    ],
)
def test_dirty_snapshot_input_makes_provenance_unavailable(tmp_path: Path, dirty_path: str) -> None:
    """A clean commit hash cannot describe any dirty input bytes used for rendering."""
    _init_snapshot_git_repository(tmp_path)
    dirty = tmp_path / dirty_path
    dirty.parent.mkdir(parents=True, exist_ok=True)
    dirty.write_text("dirty\n", encoding="utf-8")

    assert _snapshot_source_revision(tmp_path) == "unavailable"


def test_dirty_generated_outputs_do_not_invalidate_snapshot_provenance(tmp_path: Path) -> None:
    _init_snapshot_git_repository(tmp_path)
    before = _snapshot_source_revision(tmp_path)
    (tmp_path / "coordination/CURRENT.md").write_text("dirty output\n", encoding="utf-8")
    (tmp_path / "coordination/BOARD.md").write_text("dirty output\n", encoding="utf-8")

    assert _snapshot_source_revision(tmp_path) == before


def test_fixed_clock_snapshot_reproduces_committed_bytes_after_output_only_commit(
    tmp_path: Path,
) -> None:
    """A final output-only commit must not alter the provenance rendered into its own snapshots."""
    _init_snapshot_git_repository(tmp_path)
    fixed_time = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
    write_initial_snapshots(tmp_path, fixed_time)
    _git(tmp_path, "add", "coordination/CURRENT.md", "coordination/BOARD.md")
    _git(tmp_path, "commit", "-m", "generated snapshots")
    expected = {
        path: (tmp_path / path).read_bytes()
        for path in ("coordination/CURRENT.md", "coordination/BOARD.md")
    }

    write_initial_snapshots(tmp_path, fixed_time)

    assert {
        path: (tmp_path / path).read_bytes()
        for path in ("coordination/CURRENT.md", "coordination/BOARD.md")
    } == expected


def test_fresh_codegraph_stays_fresh_across_two_fixed_clock_snapshot_generations(
    tmp_path: Path,
) -> None:
    """Generated snapshots must not enter graph inputs and turn Fresh into Stale."""
    _init_snapshot_git_repository(tmp_path)
    build_codegraph(tmp_path, FIXED_TIME)

    write_initial_snapshots(tmp_path, FIXED_TIME)
    first = {
        path: (tmp_path / path).read_bytes()
        for path in ("coordination/CURRENT.md", "coordination/BOARD.md")
    }
    write_initial_snapshots(tmp_path, FIXED_TIME)
    second = {
        path: (tmp_path / path).read_bytes()
        for path in ("coordination/CURRENT.md", "coordination/BOARD.md")
    }

    assert (
        b"Fresh: the manifest source-tree digest matches tracked inputs."
        in first["coordination/CURRENT.md"]
    )
    assert first == second


def test_snapshot_freshness_uses_configured_alternate_codegraph(tmp_path: Path) -> None:
    """Snapshot freshness must read the same configured manifest that build writes."""
    _init_snapshot_git_repository(tmp_path)
    project = tmp_path / "coordination/project.yaml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            "codegraph: coordination/codegraph",
            "codegraph: coordination/generated/graph",
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "coordination/project.yaml")
    _git(tmp_path, "commit", "-m", "configure alternate graph")
    build_codegraph(tmp_path, FIXED_TIME)

    write_initial_snapshots(tmp_path, FIXED_TIME)
    first = (tmp_path / "coordination/CURRENT.md").read_bytes()
    write_initial_snapshots(tmp_path, FIXED_TIME)

    assert b"Fresh: the manifest source-tree digest matches tracked inputs." in first
    assert (tmp_path / "coordination/CURRENT.md").read_bytes() == first


@pytest.mark.parametrize(
    "handoff",
    [
        "coordination/handoffs/x>\n## forged",
        "javascript:alert(1)",
        "javascript&colon;alert",
        "coordination/%2e%2e/BOARD.md",
        r"coordination\\handoffs\\x.md",
        "../coordination/handoffs/x.md",
        "/coordination/handoffs/x.md",
        "coordination/handoffs/x\u0085.md",
        "coordination/handoffs/x\u2028.md",
        "coordination/handoffs/x\u2029.md",
    ],
)
def test_board_export_rejects_unsafe_relative_handoff_links(handoff: str) -> None:
    """Accepting a malformed handoff target would let untrusted board data forge a link."""
    with pytest.raises(ValidationError):
        BoardExport.model_validate(
            {
                "project_url": "https://github.com/users/Ven-Z8/projects/1",
                "items": [
                    {
                        "task_id": "AO-D01-01",
                        "title": "Safe title",
                        "status": "ready",
                        "priority": "P0",
                        "handoff": handoff,
                    }
                ],
            }
        )


def test_board_export_renders_safe_normalized_relative_handoff_link() -> None:
    export = BoardExport.model_validate(
        {
            "project_url": "https://github.com/users/Ven-Z8/projects/1",
            "items": [
                {
                    "task_id": "AO-D01-01",
                    "title": "Safe title",
                    "status": "ready",
                    "priority": "P0",
                    "handoff": "coordination/handoffs/2026-08-30--AO-D01-01--codex.md",
                }
            ],
        }
    )

    rendered = render_board(export, FIXED_TIME)

    assert "[handoff](<coordination/handoffs/2026-08-30--AO-D01-01--codex.md>)" in rendered


def _init_snapshot_git_repository(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "tests@example.test")
    _git(root, "config", "user.name", "Snapshot Tests")
    seed_control_room(root)
    artifacts = root / "coordination/artifacts/index.yaml"
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("schema_version: 1\nartifacts: []\n", encoding="utf-8")
    (root / "app/project_control").mkdir(parents=True)
    (root / "app/project_control/snapshots.py").write_text("source\n", encoding="utf-8")
    (root / "coordination/CURRENT.md").write_text("output\n", encoding="utf-8")
    (root / "coordination/BOARD.md").write_text("output\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture inputs")


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True, text=True)
