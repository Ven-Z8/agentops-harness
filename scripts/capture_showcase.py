from __future__ import annotations

import argparse
import contextlib
import json
import re
import shutil
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.core.run_artifacts import artifact_dir_for_run
from app.core.showcase import (
    ShowcaseError,
    ShowcaseFixture,
    load_showcase_fixture,
    unsafe_showcase_content,
)
from app.core.storage import RunStorage
from app.schemas.run import RunRecord
from app.schemas.showcase import SHOWCASE_MANIFEST_ARTIFACT, ShowcaseManifest

SHOWCASE_RUN_ID = "showcase-governed-migration"
SHOWCASE_REPO_PATH = "examples/showcase/fixtures/pydantic-v1-app"
SHOWCASE_ARTIFACT_PATH = "examples/showcase/governed-migration/artifacts"
SHOWCASE_STORAGE_PATH = ".agentops/showcase.db"
HARNESS_ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_MIGRATION_FILES = frozenset({"app/models.py", "app/service.py"})

_TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".md", ".patch", ".log", ".txt"}
CAPTURE_ARTIFACT_ALLOWLIST = frozenset(
    {
        "capability_pack.json",
        "conflict_report.json",
        "diff.patch",
        "evidence_report.json",
        "final_report.md",
        "impacted_graph.json",
        "openhands_events.jsonl",
        "permission_report.json",
        "product_review.json",
        "repo_graph.json",
        "repo_profile.json",
        "risk_report.json",
        "task_plan.yaml",
        "test_results.json",
        "trace.jsonl",
        "verification_bundle.json",
        "worker_loop_summary.json",
        "worker_packet.md",
        "worker_prompt.md",
        "worker_result.json",
        "worker_scorecard.json",
        "workspace_report.json",
    }
)
OMITTED_NORMAL_ARTIFACTS = frozenset(
    {"run_record.json", "worker_stderr.log", "worker_stdout.log"}
)
PROVIDER_STATE_DIRECTORY = "openhands_state"
OMITTED_INTERNAL_OUTPUT = "showcase://omitted-internal-output"


def _path_aliases(path: Path) -> set[str]:
    aliases = {str(path)}
    with contextlib.suppress(OSError):
        aliases.add(str(path.resolve()))
    return {alias for alias in aliases if alias not in {"", "."}}


def _replace_exact_value(text: str, source: str, replacement: str) -> str:
    """Replace exact values even when terminal rendering inserted soft line wraps."""
    text = text.replace(source, replacement)
    if not source.startswith(("/", "\\")):
        return text
    optional_soft_wrap = r"(?:[ \t]*(?:\\n|\r?\n)[ \t]*)?"
    pattern = optional_soft_wrap.join(re.escape(character) for character in source)
    return re.sub(pattern, lambda _match: replacement, text)


def sanitize_text(
    text: str,
    *,
    source_root: Path,
    source_run_id: str | None = None,
    artifact_dir: Path | None = None,
    storage_path: Path | None = None,
    harness_root: Path | None = None,
) -> str:
    """Rewrite capture-specific identifiers and reject unsafe residual text."""
    replacements: list[tuple[str, str]] = []
    replacements.extend((value, SHOWCASE_REPO_PATH) for value in _path_aliases(source_root))
    if artifact_dir is not None:
        replacements.extend(
            (value, SHOWCASE_ARTIFACT_PATH) for value in _path_aliases(artifact_dir)
        )
    if storage_path is not None:
        replacements.extend(
            (value, SHOWCASE_STORAGE_PATH) for value in _path_aliases(storage_path)
        )
    replacements.extend(
        (value, ".") for value in _path_aliases(harness_root or HARNESS_ROOT)
    )
    if source_run_id:
        replacements.append((source_run_id, SHOWCASE_RUN_ID))

    sanitized = text
    for source, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        sanitized = _replace_exact_value(sanitized, source, replacement)

    unsafe = unsafe_showcase_content(sanitized)
    if unsafe:
        raise ShowcaseError(f"Capture contains {unsafe}")
    return sanitized


def sanitize_record(
    record: RunRecord,
    source_root: Path,
    *,
    artifact_dir: Path | None = None,
    storage_path: Path | None = None,
) -> RunRecord:
    payload = sanitize_text(
        record.model_dump_json(),
        source_root=source_root,
        source_run_id=record.run_id,
        artifact_dir=artifact_dir,
        storage_path=storage_path,
    )
    sanitized = RunRecord.model_validate_json(payload)
    sanitized.run_id = SHOWCASE_RUN_ID
    sanitized.repo_path = SHOWCASE_REPO_PATH
    return sanitized


def _worker_events(artifact_dir: Path) -> list[dict]:
    events_path = artifact_dir / "openhands_events.jsonl"
    if not events_path.is_file():
        return []
    events: list[dict] = []
    for line_number, line in enumerate(
        events_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ShowcaseError(
                f"Worker event log contains invalid JSON on line {line_number}"
            ) from exc
        if not isinstance(payload, dict):
            raise ShowcaseError(f"Worker event {line_number} must be a JSON object")
        events.append(payload)
    return events


def _validate_capture(record: RunRecord, artifact_dir: Path) -> None:
    if record.status != "completed":
        raise ShowcaseError(f"Showcase source run must be completed, got {record.status!r}")
    if not _worker_events(artifact_dir):
        raise ShowcaseError("Showcase source run must contain observable worker events")
    if record.capability_pack is None or record.capability_pack.name != "pydantic-v2":
        raise ShowcaseError("Showcase source run must use the pydantic-v2 capability pack")
    if not record.changed_files:
        raise ShowcaseError("Showcase source run must contain at least one changed file")
    if (
        len(record.changed_files) != len(CONTROLLED_MIGRATION_FILES)
        or set(record.changed_files) != CONTROLLED_MIGRATION_FILES
    ):
        raise ShowcaseError(
            "Showcase source run must change exactly the controlled migration files: "
            "app/models.py and app/service.py"
        )
    if not record.test_results.commands:
        raise ShowcaseError("Showcase source run must contain harness test results")
    if any(command.exit_code != 0 for command in record.test_results.commands):
        raise ShowcaseError("Showcase source run must have all harness tests passing")
    if not record.evidence_report.grounded:
        raise ShowcaseError("Showcase source run must contain grounded evidence")
    if not record.verification_bundle.checks:
        raise ShowcaseError("Showcase source run must contain verification checks")
    if not record.verification_bundle.accepted:
        raise ShowcaseError("Showcase source run must contain accepted verification")


def _copy_sanitized_artifacts(
    source: Path,
    destination: Path,
    *,
    source_root: Path,
    source_run_id: str,
    storage_path: Path,
) -> None:
    destination.mkdir(parents=True)
    for path in sorted(source.iterdir(), key=lambda item: item.name):
        if path.name == PROVIDER_STATE_DIRECTORY and path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink():
            raise ShowcaseError(f"Capture artifact must not be a symbolic link: {path.name}")
        if path.is_dir():
            raise ShowcaseError(f"Capture contains an unexpected artifact directory: {path.name}")
        if path.name not in CAPTURE_ARTIFACT_ALLOWLIST | OMITTED_NORMAL_ARTIFACTS:
            raise ShowcaseError(f"Capture contains an unexpected capture artifact: {path.name}")
        if path.suffix not in _TEXT_SUFFIXES:
            raise ShowcaseError(f"Capture contains an unsupported binary artifact: {path.name}")
        text = path.read_text(encoding="utf-8", errors="strict")
        if path.name == "openhands_events.jsonl":
            sanitized = _sanitize_worker_event_log(
                text,
                source_root=source_root,
                source_run_id=source_run_id,
                artifact_dir=source,
                storage_path=storage_path,
            )
        else:
            sanitized = sanitize_text(
                text,
                source_root=source_root,
                source_run_id=source_run_id,
                artifact_dir=source,
                storage_path=storage_path,
            )
        if path.name in OMITTED_NORMAL_ARTIFACTS:
            continue
        (destination / path.name).write_text(sanitized, encoding="utf-8")


def _sanitize_worker_event_log(
    text: str,
    *,
    source_root: Path,
    source_run_id: str,
    artifact_dir: Path,
    storage_path: Path,
) -> str:
    provider_state_aliases = _path_aliases(artifact_dir / PROVIDER_STATE_DIRECTORY)
    sanitized_lines: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ShowcaseError(
                f"Worker event log contains invalid JSON on line {line_number}"
            ) from exc
        if not isinstance(event, dict):
            raise ShowcaseError(f"Worker event {line_number} must be a JSON object")
        event = _sanitize_worker_event_value(event, provider_state_aliases)
        serialized = json.dumps(event, sort_keys=False)
        sanitized = sanitize_text(
            serialized,
            source_root=source_root,
            source_run_id=source_run_id,
            artifact_dir=artifact_dir,
            storage_path=storage_path,
        )
        sanitized_lines.append(sanitized)
    return "".join(f"{line}\n" for line in sanitized_lines)


def _sanitize_worker_event_value(
    value: object,
    provider_state_aliases: set[str],
    *,
    key: str | None = None,
) -> object:
    if isinstance(value, dict):
        return {
            item_key: _sanitize_worker_event_value(
                item_value,
                provider_state_aliases,
                key=item_key,
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_worker_event_value(item, provider_state_aliases, key=key)
            for item in value
        ]
    if key == "hostname":
        return "portfolio-host"
    if key == "username":
        return "portfolio-user"
    if key in {
        "full_output_save_dir",
        "persistence_dir",
        "provider_state_path",
        "state_dir",
    }:
        return OMITTED_INTERNAL_OUTPUT
    if isinstance(value, str):
        sanitized = value
        for alias in sorted(provider_state_aliases, key=len, reverse=True):
            sanitized = sanitized.replace(alias, OMITTED_INTERNAL_OUTPUT)
        return sanitized
    return value


def _write_fixture(
    staging: Path,
    *,
    record: RunRecord,
    source_record: RunRecord,
    source_artifacts: Path,
    source_root: Path,
    storage: Path,
    source_commit: str,
) -> None:
    artifacts = staging / "artifacts"
    _copy_sanitized_artifacts(
        source_artifacts,
        artifacts,
        source_root=source_root,
        source_run_id=source_record.run_id,
        storage_path=storage,
    )
    required_artifacts = sorted(
        [path.name for path in artifacts.iterdir() if path.is_file()]
        + [SHOWCASE_MANIFEST_ARTIFACT]
    )
    manifest = ShowcaseManifest(
        mission_id="governed-migration",
        run_id=SHOWCASE_RUN_ID,
        source_run_id=source_record.run_id,
        target_fixture=SHOWCASE_REPO_PATH,
        source_commit=source_commit,
        captured_at=datetime.now(UTC),
        pack=record.capability_pack,
        required_artifacts=required_artifacts,
        sanitation_notes=[
            "Rewrote the source repository, capture storage, artifact directory, and run ID.",
            "Neutralized worker host, user, and internal output-path metadata.",
            "Rejected credentials, private provider state, and residual machine paths.",
            "Copied only inspectable allowlisted artifacts; preserved observable event order.",
        ],
    )
    manifest_payload = manifest.model_dump(mode="json")
    (staging / "manifest.yaml").write_text(
        yaml.safe_dump(manifest_payload, sort_keys=False),
        encoding="utf-8",
    )
    (staging / "run_record.json").write_text(
        record.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (artifacts / SHOWCASE_MANIFEST_ARTIFACT).write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def capture_showcase(
    *,
    storage: Path,
    run_id: str,
    source_root: Path,
    source_commit: str,
    output: Path,
) -> ShowcaseFixture:
    source_record = RunStorage(storage).get(run_id)
    source_artifacts = artifact_dir_for_run(storage, run_id)
    if not source_artifacts.is_dir():
        raise ShowcaseError(f"Showcase source artifacts are missing: {source_artifacts}")
    if not source_commit.strip():
        raise ShowcaseError("Showcase source commit must not be empty")
    _validate_capture(source_record, source_artifacts)
    sanitized_record = sanitize_record(
        source_record,
        source_root,
        artifact_dir=source_artifacts,
        storage_path=storage,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ShowcaseError(f"Showcase output must not be a symbolic link: {output}")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.capture-", dir=output.parent)
    )
    backup: Path | None = None
    installed = False
    try:
        _write_fixture(
            staging,
            record=sanitized_record,
            source_record=source_record,
            source_artifacts=source_artifacts,
            source_root=source_root,
            storage=storage,
            source_commit=source_commit,
        )
        load_showcase_fixture(staging)
        if output.exists():
            backup = output.with_name(f".{output.name}.backup-{uuid.uuid4().hex}")
            output.rename(backup)
        try:
            staging.rename(output)
            installed = True
            fixture = load_showcase_fixture(output)
        except Exception:
            if installed:
                shutil.rmtree(output, ignore_errors=True)
            if backup is not None and backup.exists():
                backup.rename(output)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return fixture
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists() and not output.exists():
            backup.rename(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        fixture = capture_showcase(
            storage=args.storage,
            run_id=args.run_id,
            source_root=args.source_root,
            source_commit=args.source_commit,
            output=args.output,
        )
    except (KeyError, OSError, ShowcaseError) as exc:
        print(f"showcase capture failed: {exc}", file=sys.stderr)
        return 2
    print(f"Captured showcase run {fixture.record.run_id} at {fixture.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
