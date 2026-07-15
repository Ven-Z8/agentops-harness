from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from app.core.run_artifacts import artifact_dir_for_run, artifact_root_for_storage
from app.core.storage import RunStorage
from app.schemas.run import RunRecord
from app.schemas.showcase import SHOWCASE_MANIFEST_ARTIFACT, ShowcaseManifest

_TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".md", ".patch", ".log", ".txt"}
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Z0-9_.-])"
    r"(?P<name>[A-Z0-9_.-]*(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET|ACCESS[_-]?KEY)"
    r"[A-Z0-9_.-]*)\s*[:=]\s*"
    r"(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s,;}\]]+)"
)
_AUTHORIZATION_BEARER = re.compile(
    r"(?i)\bauthorization\s*[:=]\s*[\"']?bearer\s+[^\s\"',;}\]]+"
)
_OPENROUTER_KEY = re.compile(r"(?i)(?<![A-Z0-9_-])sk-or-v1-[A-Z0-9_-]{4,}")
_PROVIDER_STATE = re.compile(
    r"(?i)(?:openhands[_-]state|provider[_-]request(?:\.[a-z0-9._-]+)?)"
)
_UNSAFE_PATH = re.compile(
    r"(?i)(?:/Volumes/|/Users/|/home/|/root/|/private/tmp/|/tmp/|/var/tmp/|"
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


@dataclass(frozen=True)
class ShowcaseFixture:
    root: Path
    manifest: ShowcaseManifest
    record: RunRecord
    artifacts_dir: Path


class ShowcaseError(ValueError):
    pass


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


def unsafe_showcase_content(text: str) -> str | None:
    """Name the first credential, provider-state, or machine-path marker in text."""
    if _AUTHORIZATION_BEARER.search(text):
        return "authorization bearer credential"
    if _OPENROUTER_KEY.search(text):
        return "OpenRouter-shaped key"
    credential = _unsafe_credential_assignment(text)
    if credential:
        return f"credential-like value assignment {credential.group('name')}="
    unsafe_path = _UNSAFE_PATH.search(text)
    if unsafe_path:
        return f"unsafe home or temporary path: {unsafe_path.group(0)!r}"
    provider_state = _PROVIDER_STATE.search(text)
    if provider_state:
        return f"provider-state marker {provider_state.group(0)!r}"
    return None


def _provider_state_path_marker(path: Path, root: Path) -> str | None:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    marker = _PROVIDER_STATE.search(relative)
    return marker.group(0) if marker else None


def load_showcase_fixture(root: Path) -> ShowcaseFixture:
    manifest_path = root / "manifest.yaml"
    record_path = root / "run_record.json"
    artifacts_dir = root / "artifacts"
    try:
        manifest = ShowcaseManifest.model_validate(
            yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        )
        record = RunRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ShowcaseError(f"Invalid showcase fixture at {root}: {exc}") from exc

    if manifest.run_id != record.run_id:
        raise ShowcaseError(
            f"Manifest run_id {manifest.run_id!r} does not match record {record.run_id!r}"
        )
    run_id_paths = (PurePosixPath(record.run_id), PureWindowsPath(record.run_id))
    if record.run_id in {".", ".."} or any(
        path.is_absolute() or len(path.parts) != 1 or path.name != record.run_id
        for path in run_id_paths
    ):
        raise ShowcaseError(
            f"Showcase run_id must be a safe single path component: {record.run_id!r}"
        )
    if record.capability_pack != manifest.pack:
        raise ShowcaseError("Manifest pack does not match RunRecord capability_pack")

    for name in manifest.required_artifacts:
        if Path(name).name != name:
            raise ShowcaseError(f"Artifact name must be a basename: {name}")
        path = artifacts_dir / name
        if not path.is_file():
            raise ShowcaseError(f"Required showcase artifact is missing: {name}")

    for path in sorted(root.rglob("*")):
        provider_marker = _provider_state_path_marker(path, root)
        if provider_marker:
            raise ShowcaseError(
                f"Unsafe provider-state marker {provider_marker!r} remains in fixture path"
            )
        if path.is_file() and path.suffix in _TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            unsafe = unsafe_showcase_content(text)
            if unsafe:
                raise ShowcaseError(f"Unsafe {unsafe} remains in {path.name}")

    return ShowcaseFixture(root, manifest, record, artifacts_dir)


def import_showcase(root: Path, storage_path: Path) -> RunRecord:
    fixture = load_showcase_fixture(root)
    destination = artifact_dir_for_run(storage_path, fixture.record.run_id)
    if destination.is_symlink():
        raise ShowcaseError(
            f"Showcase artifact destination must not be a symbolic link for run_id "
            f"{fixture.record.run_id!r}: {destination}"
        )

    artifact_root = artifact_root_for_storage(storage_path).resolve()
    resolved_destination = destination.resolve()
    if resolved_destination.parent != artifact_root:
        raise ShowcaseError(
            f"Unsafe showcase artifact destination for run_id {fixture.record.run_id!r}: "
            f"{resolved_destination} is not a direct child of {artifact_root}"
        )

    RunStorage(storage_path).save(fixture.record)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture.artifacts_dir, destination)
    (destination / SHOWCASE_MANIFEST_ARTIFACT).write_text(
        json.dumps(fixture.manifest.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return fixture.record
