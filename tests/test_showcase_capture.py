import json
from pathlib import Path

import pytest
import yaml

from app.core.run_artifacts import artifact_dir_for_run
from app.core.showcase import ShowcaseError, load_showcase_fixture
from app.core.storage import RunStorage
from app.schemas.pack import CapabilityPackProvenance
from app.schemas.test import CommandResult
from app.schemas.verification import VerifierScope
from scripts.capture_showcase import capture_showcase, sanitize_record, sanitize_text
from tests.helpers_runrecord import minimal_run_record


def _capturable_run(storage: Path, source_root: Path) -> str:
    record = minimal_run_record()
    record.run_id = "source-run-123"
    record.repo_path = str(source_root)
    record.changed_files = ["app/models.py", "app/service.py"]
    record.capability_pack = CapabilityPackProvenance(
        name="pydantic-v2",
        domain="python-migration",
        version="1.0.0",
        description="Pydantic migration playbook",
        skills=["migration-playbook.md"],
        resolved_tools=["terminal", "file_editor", "grep", "glob"],
        hooks=[],
        manifest_sha256="a" * 64,
    )
    record.test_results.commands = [
        CommandResult(
            command="python -m pytest -q",
            exit_code=0,
            duration_seconds=0.2,
            stdout="2 passed",
        )
    ]
    record.verification_bundle.checks = [
        VerifierScope(
            name="tests",
            verdict="pass",
            confidence="high",
            verifies="focused behavior",
            cannot_verify="production traffic",
        )
    ]
    RunStorage(storage).save(record)
    return record.run_id


def test_sanitize_text_replaces_machine_paths_and_rejects_secrets(
    tmp_path: Path,
) -> None:
    text = "repo=/Users/venkat/work/demo token=OPENAI_API_KEY=secret"

    with pytest.raises(ShowcaseError, match="credential-like value"):
        sanitize_text(text, source_root=Path("/Users/venkat/work/demo"))


def test_sanitize_text_rewrites_exact_harness_root_to_project_relative_path() -> None:
    harness_root = Path("/Volumes/VeN/worktrees/agentops-harness")
    text = (
        "python=/Volumes/VeN/worktrees/agentops-harness/.venv/bin/python "
        "cwd=/Volumes/VeN/worktrees/agentops-harness"
    )

    sanitized = sanitize_text(
        text,
        source_root=Path("/Volumes/VeN/captures/pydantic-v1-app"),
        harness_root=harness_root,
    )

    assert sanitized == "python=./.venv/bin/python cwd=."


def test_sanitize_text_rewrites_soft_wrapped_exact_source_path() -> None:
    source_root = Path(
        "/Volumes/VeN/worktrees/agentops-harness/"
        ".superpowers/captures/pydantic-v1-app"
    )
    wrapped = (
        "/Volumes/VeN/worktrees/agentops-har               \\n"
        "                             ness/"
        ".superpowers/captures/pydantic-v1-app/app/models.py"
    )

    sanitized = sanitize_text(f"file={wrapped}", source_root=source_root)

    assert sanitized == (
        "file=examples/showcase/fixtures/pydantic-v1-app/app/models.py"
    )


@pytest.mark.parametrize(
    "telemetry",
    [
        r"completionTokens: \n4998",
        "Tokens: ↑",
        r"nTokens: \u2191",
    ],
)
def test_sanitize_text_allows_safe_token_usage_telemetry(telemetry: str) -> None:
    assert sanitize_text(telemetry, source_root=Path("/capture/repo")) == telemetry


def test_sanitize_text_rejects_residual_workspace_volume_path() -> None:
    text = "cache=/Volumes/VeN/ollama/models/cache.bin"

    with pytest.raises(ShowcaseError, match="unsafe home or temporary path"):
        sanitize_text(
            text,
            source_root=Path("/Volumes/VeN/captures/pydantic-v1-app"),
            harness_root=Path("/Volumes/VeN/worktrees/agentops-harness"),
        )


def test_capture_rewrites_repo_root_without_changing_semantic_results(
    tmp_path: Path,
) -> None:
    record = minimal_run_record()
    record.run_id = "source-run-123"
    record.repo_path = "/private/tmp/capture/pydantic-v1-app"

    sanitized = sanitize_record(record, Path(record.repo_path))

    assert sanitized.run_id == "showcase-governed-migration"
    assert sanitized.repo_path == "examples/showcase/fixtures/pydantic-v1-app"
    assert sanitized.status == record.status
    assert sanitized.test_results == record.test_results
    assert sanitized.verification_bundle == record.verification_bundle


def test_capture_failure_preserves_existing_output(tmp_path: Path) -> None:
    source_root = tmp_path / "capture" / "pydantic-v1-app"
    source_root.mkdir(parents=True)
    storage = tmp_path / "capture" / "capture.db"
    run_id = _capturable_run(storage, source_root)
    artifacts = artifact_dir_for_run(storage, run_id)
    artifacts.mkdir(parents=True)
    (artifacts / "openhands_events.jsonl").write_text(
        json.dumps({"event_type": "ActionEvent", "event": {"tool_name": "terminal"}})
        + "\n",
        encoding="utf-8",
    )
    (artifacts / "worker_stdout.log").write_text(
        "ANTHROPIC_API_KEY=must-not-survive\n",
        encoding="utf-8",
    )
    output = tmp_path / "governed-migration"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("existing fixture\n", encoding="utf-8")

    with pytest.raises(ShowcaseError, match="credential-like value"):
        capture_showcase(
            storage=storage,
            run_id=run_id,
            source_root=source_root,
            source_commit="1" * 40,
            output=output,
        )

    assert sentinel.read_text(encoding="utf-8") == "existing fixture\n"
    assert not list(tmp_path.glob(".governed-migration.capture-*"))


def test_capture_rejects_changes_outside_controlled_migration_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "capture" / "pydantic-v1-app"
    source_root.mkdir(parents=True)
    storage = tmp_path / "capture" / "capture.db"
    run_id = _capturable_run(storage, source_root)
    record = RunStorage(storage).get(run_id)
    record.changed_files = ["app/models.py", "pyproject.toml"]
    RunStorage(storage).save(record)
    artifacts = artifact_dir_for_run(storage, run_id)
    artifacts.mkdir(parents=True)
    (artifacts / "openhands_events.jsonl").write_text(
        json.dumps({"event_type": "ActionEvent", "event": {"tool_name": "terminal"}})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ShowcaseError, match="controlled migration files"):
        capture_showcase(
            storage=storage,
            run_id=run_id,
            source_root=source_root,
            source_commit="3" * 40,
            output=tmp_path / "governed-migration",
        )


def test_capture_rejects_unaccepted_verification(tmp_path: Path) -> None:
    source_root = tmp_path / "capture" / "pydantic-v1-app"
    source_root.mkdir(parents=True)
    storage = tmp_path / "capture" / "capture.db"
    run_id = _capturable_run(storage, source_root)
    record = RunStorage(storage).get(run_id)
    record.verification_bundle.checks[0].verdict = "fail"
    RunStorage(storage).save(record)
    artifacts = artifact_dir_for_run(storage, run_id)
    artifacts.mkdir(parents=True)
    (artifacts / "openhands_events.jsonl").write_text(
        json.dumps({"event_type": "ActionEvent", "event": {"tool_name": "terminal"}})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ShowcaseError, match="accepted verification"):
        capture_showcase(
            storage=storage,
            run_id=run_id,
            source_root=source_root,
            source_commit="4" * 40,
            output=tmp_path / "governed-migration",
        )


def test_capture_preserves_worker_event_order_and_omits_provider_state(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "capture" / "pydantic-v1-app"
    source_root.mkdir(parents=True)
    storage = tmp_path / "capture" / "capture.db"
    run_id = _capturable_run(storage, source_root)
    artifacts = artifact_dir_for_run(storage, run_id)
    artifacts.mkdir(parents=True)
    source_events = [
        {"event_type": "ActionEvent", "event": {"tool_name": "grep"}},
        {"event_type": "ObservationEvent", "event": {"content": "matches"}},
        {"event_type": "ActionEvent", "event": {"tool_name": "file_editor"}},
    ]
    (artifacts / "openhands_events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in source_events),
        encoding="utf-8",
    )
    (artifacts / "trace.jsonl").write_text(
        json.dumps({"index": 0, "event": "scan_repo:start", "run_id": run_id}) + "\n",
        encoding="utf-8",
    )
    provider_state = artifacts / "openhands_state"
    provider_state.mkdir()
    (provider_state / "requests.json").write_text(
        '{"provider_request": "internal"}\n',
        encoding="utf-8",
    )
    output = tmp_path / "governed-migration"

    fixture = capture_showcase(
        storage=storage,
        run_id=run_id,
        source_root=source_root,
        source_commit="2" * 40,
        output=output,
    )

    captured_events = [
        json.loads(line)
        for line in (output / "artifacts" / "openhands_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert captured_events == source_events
    assert manifest["source_run_id"] == run_id
    assert manifest["source_commit"] == "2" * 40
    assert not (output / "artifacts" / "openhands_state").exists()
    assert (output / "artifacts" / "showcase_manifest.json").is_file()
    assert fixture == load_showcase_fixture(output)
