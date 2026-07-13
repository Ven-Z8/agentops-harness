from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from app.core.run_artifacts import artifact_dir_for_run, artifact_root_for_storage
from app.core.storage import RunStorage
from app.schemas.run import RunRecord
from app.schemas.showcase import SHOWCASE_MANIFEST_ARTIFACT, ShowcaseManifest

_TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".md", ".patch", ".log", ".txt"}
_FORBIDDEN_MARKERS = (
    "/Users/",
    "/home/",
    "/private/tmp/",
    "API_KEY=",
    "TOKEN=",
    "PASSWORD=",
)


@dataclass(frozen=True)
class ShowcaseFixture:
    root: Path
    manifest: ShowcaseManifest
    record: RunRecord
    artifacts_dir: Path


class ShowcaseError(ValueError):
    pass


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
        if path.is_file() and path.suffix in _TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            marker = next((item for item in _FORBIDDEN_MARKERS if item in text), None)
            if marker:
                raise ShowcaseError(f"Unsafe marker {marker!r} remains in {path.name}")

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
