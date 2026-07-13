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
from app.core.showcase import ShowcaseError, ShowcaseFixture, load_showcase_fixture
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
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Z0-9_.-])"
    r"(?P<name>[A-Z0-9_.-]*(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET|ACCESS[_-]?KEY)"
    r"[A-Z0-9_.-]*)\s*[:=]\s*"
    r"(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s,;}\]]+)"
)
_UNSAFE_PATH = re.compile(
    r"(?i)(?:/Volumes/|/Users/|/home/|/private/tmp/|/tmp/|/var/tmp/|"
    r"/var/folders/|[A-Z]:\\Users\\)"
)
_TOKEN_USAGE_NAMES = {
    "tokens",
    "ntokens",
    "prompttokens",
    "completiontokens",
    "totaltokens",
    "inputtokens",
    "outputtokens",
    "reasoningtokens",
    "cachedtokens",
    "cachetokens",
}
_TOKEN_USAGE_VALUE = re.compile(
    r"(?i)(?:\\n)*\d+(?:\.\d+)?|[\u2191\u2193]|\\u219[13]"
)


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


def _unsafe_credential_assignment(text: str) -> re.Match[str] | None:
    for match in _CREDENTIAL_ASSIGNMENT.finditer(text):
        metric_name = re.sub(r"[^a-z0-9]", "", match.group("name").lower())
        metric_value = match.group("value").strip()
        if (
            metric_name in _TOKEN_USAGE_NAMES
            and _TOKEN_USAGE_VALUE.fullmatch(metric_value)
        ):
            continue
        return match
    return None


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

    credential = _unsafe_credential_assignment(sanitized)
    if credential:
        raise ShowcaseError("Capture contains a credential-like value assignment")
    unsafe_path = _UNSAFE_PATH.search(sanitized)
    if unsafe_path:
        raise ShowcaseError(
            f"Capture contains an unsafe home or temporary path: {unsafe_path.group(0)!r}"
        )
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
        if path.name == "openhands_state":
            continue
        if path.is_symlink():
            raise ShowcaseError(f"Capture artifact must not be a symbolic link: {path.name}")
        if path.is_dir():
            raise ShowcaseError(f"Capture contains an unexpected artifact directory: {path.name}")
        if path.suffix not in _TEXT_SUFFIXES:
            raise ShowcaseError(f"Capture contains an unsupported binary artifact: {path.name}")
        text = path.read_text(encoding="utf-8", errors="strict")
        sanitized = sanitize_text(
            text,
            source_root=source_root,
            source_run_id=source_run_id,
            artifact_dir=source,
            storage_path=storage_path,
        )
        (destination / path.name).write_text(sanitized, encoding="utf-8")


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
            "Rejected credential-like assignments and residual home or temporary paths.",
            "Excluded OpenHands provider persistence state; preserved observable event order.",
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
        staging.rename(output)
        try:
            fixture = load_showcase_fixture(output)
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            if backup is not None:
                backup.rename(output)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return fixture
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


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
