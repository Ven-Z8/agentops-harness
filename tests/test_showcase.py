import json
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api import create_api
from app.cockpit.artifacts import CockpitReader
from app.core.run_artifacts import artifact_dir_for_run, artifact_root_for_storage
from app.core.showcase import ShowcaseError, import_showcase, load_showcase_fixture
from app.core.storage import RunStorage
from app.schemas.pack import CapabilityPackProvenance
from scripts import showcase as showcase_script
from tests.helpers_runrecord import minimal_run_record

COMMITTED_SHOWCASE = Path("examples/showcase/governed-migration")


def write_showcase_fixture(root: Path) -> Path:
    record = minimal_run_record()
    record.run_id = "showcase-governed-migration"
    record.capability_pack = CapabilityPackProvenance(
        name="governed-migration",
        domain="database-migrations",
        version="1.0.0",
        description="Safe schema migration playbook",
        skills=["migration.md"],
        resolved_tools=["terminal"],
        hooks=["review_migration"],
        manifest_sha256="a" * 64,
    )

    root.mkdir(parents=True)
    (root / "artifacts").mkdir()
    (root / "run_record.json").write_text(
        record.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "mission_id": "governed-migration",
                "run_id": record.run_id,
                "source_run_id": "source-capture-123",
                "target_fixture": "examples/sample_fastapi_app",
                "source_commit": "1" * 40,
                "captured_at": "2026-07-13T12:00:00Z",
                "pack": record.capability_pack.model_dump(mode="json"),
                "required_artifacts": [
                    "final_report.md",
                    "verification_bundle.json",
                ],
                "sanitation_notes": ["Paths and secrets removed"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "artifacts" / "final_report.md").write_text(
        record.final_report.markdown + "\n",
        encoding="utf-8",
    )
    (root / "artifacts" / "verification_bundle.json").write_text(
        json.dumps(record.verification_bundle.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def set_showcase_run_id(fixture: Path, run_id: str) -> None:
    manifest_path = fixture / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = run_id
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    record_path = fixture / "run_record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["run_id"] = run_id
    record_path.write_text(json.dumps(record), encoding="utf-8")


def test_import_showcase_is_idempotent_and_preserves_other_runs(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / ".agentops" / "showcase.db"
    other = minimal_run_record()
    other.run_id = "other-run"
    RunStorage(storage).save(other)
    other_artifacts = artifact_dir_for_run(storage, other.run_id)
    other_artifacts.mkdir(parents=True)
    (other_artifacts / "keep.txt").write_text("keep\n", encoding="utf-8")

    first = import_showcase(fixture, storage)
    imported_artifacts = artifact_dir_for_run(storage, first.run_id)
    (imported_artifacts / "stale.txt").write_text("stale\n", encoding="utf-8")
    (fixture / "artifacts" / "final_report.md").write_text("# Updated\n", encoding="utf-8")
    second = import_showcase(fixture, storage)

    assert first.run_id == second.run_id == "showcase-governed-migration"
    assert {record.run_id for record in RunStorage(storage).list()} == {
        "other-run",
        "showcase-governed-migration",
    }
    assert not (imported_artifacts / "stale.txt").exists()
    assert (imported_artifacts / "final_report.md").read_text(encoding="utf-8") == "# Updated\n"
    assert (other_artifacts / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_import_showcase_rejects_absolute_run_id_before_mutation(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    outside = tmp_path / "outside-absolute"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    set_showcase_run_id(fixture, str(outside))
    storage = tmp_path / ".agentops" / "showcase.db"

    with pytest.raises(ShowcaseError, match=re.escape(str(outside))):
        import_showcase(fixture, storage)

    assert not storage.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_import_showcase_rejects_traversal_run_id_before_mutation(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / ".agentops" / "showcase.db"
    outside = storage.parent / "outside-traversal"
    outside.mkdir(parents=True)
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    unsafe_run_id = "../outside-traversal"
    set_showcase_run_id(fixture, unsafe_run_id)

    with pytest.raises(ShowcaseError, match=re.escape(unsafe_run_id)):
        import_showcase(fixture, storage)

    assert not storage.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_import_showcase_rejects_destination_symlink_before_mutation(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / ".agentops" / "showcase.db"
    outside = tmp_path / "outside-symlink"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    artifacts_root = artifact_root_for_storage(storage)
    artifacts_root.mkdir(parents=True)
    artifact_dir_for_run(storage, "showcase-governed-migration").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(ShowcaseError, match="showcase-governed-migration"):
        import_showcase(fixture, storage)

    assert not storage.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_import_showcase_rejects_sibling_destination_symlink_before_mutation(
    tmp_path: Path,
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / ".agentops" / "showcase.db"
    artifacts_root = artifact_root_for_storage(storage)
    sibling = artifacts_root / "other-run"
    sibling.mkdir(parents=True)
    sentinel = sibling / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    destination = artifact_dir_for_run(storage, "showcase-governed-migration")
    destination.symlink_to(sibling, target_is_directory=True)

    with pytest.raises(ShowcaseError, match="symbolic link"):
        import_showcase(fixture, storage)

    assert not storage.exists()
    assert destination.is_symlink()
    assert sibling.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_imported_showcase_uses_normal_cockpit_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / "showcase.db"
    record = import_showcase(fixture, storage)
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=storage))

    assert client.get("/cockpit/api/runs").json()["runs"][0]["run_id"] == record.run_id
    assert client.get(f"/cockpit/api/runs/{record.run_id}").status_code == 200
    assert client.get(
        f"/cockpit/api/runs/{record.run_id}/artifacts/final_report.md"
    ).status_code == 200
    bundle = client.get(f"/cockpit/api/runs/{record.run_id}/bundle.zip")
    assert bundle.status_code == 200
    assert bundle.content[:2] == b"PK"


@pytest.mark.parametrize(
    ("route", "response_kind"),
    [
        ("/cockpit/api/runs", "list"),
        ("/cockpit/api/runs/{run_id}", "detail"),
        (
            "/cockpit/api/runs/{run_id}/artifacts/final_report.md",
            "artifact",
        ),
        ("/cockpit/api/runs/{run_id}/bundle.zip", "bundle"),
        ("/cockpit/api/runs/{run_id}/stream", "stream"),
        ("/cockpit/api/runs/{run_id}/worker/stream", "stream"),
    ],
)
def test_committed_showcase_uses_every_normal_cockpit_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    response_kind: str,
) -> None:
    fixture = load_showcase_fixture(COMMITTED_SHOWCASE)
    storage = tmp_path / "showcase.db"
    record = import_showcase(COMMITTED_SHOWCASE, storage)
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=storage))
    path = route.format(run_id=record.run_id)

    if response_kind == "stream":
        seen_open = seen_event = False
        with client.stream("GET", path) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                seen_open = seen_open or line == "event: open"
                seen_event = seen_event or line == "event: event"
                if seen_open and seen_event:
                    break
        assert seen_open and seen_event
        return

    response = client.get(path)
    assert response.status_code == 200
    if response_kind == "list":
        assert record.run_id in {item["run_id"] for item in response.json()["runs"]}
    elif response_kind == "detail":
        detail = response.json()
        assert detail["record"]["run_id"] == record.run_id
        assert detail["capture"]["source_run_id"] == fixture.manifest.source_run_id
        assert detail["capture"]["source_commit"] == fixture.manifest.source_commit
    elif response_kind == "artifact":
        assert "Pydantic v2" in response.text
    else:
        assert response.content[:2] == b"PK"


def test_committed_showcase_serves_every_required_artifact_and_bundle_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_showcase_fixture(COMMITTED_SHOWCASE)
    storage = tmp_path / "showcase.db"
    record = import_showcase(COMMITTED_SHOWCASE, storage)
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=storage))

    for name in fixture.manifest.required_artifacts:
        response = client.get(
            f"/cockpit/api/runs/{record.run_id}/artifacts/{name}"
        )
        assert response.status_code == 200, name

    bundle = client.get(f"/cockpit/api/runs/{record.run_id}/bundle.zip")
    assert bundle.status_code == 200
    with zipfile.ZipFile(BytesIO(bundle.content)) as archive:
        assert set(fixture.manifest.required_artifacts) <= set(archive.namelist())


def test_imported_showcase_exposes_capture_metadata_through_normal_detail(
    tmp_path: Path,
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / "showcase.db"

    record = import_showcase(fixture, storage)
    detail = CockpitReader(storage).detail(record.run_id)

    assert detail["capture"] == {
        "source_run_id": "source-capture-123",
        "source_commit": "1" * 40,
        "captured_at": "2026-07-13T12:00:00+00:00",
    }
    assert "showcase_manifest.json" in {
        artifact["name"] for artifact in detail["artifacts"]
    }


def test_showcase_bundle_includes_sanitized_manifest_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / "showcase.db"
    record = import_showcase(fixture, storage)
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=storage))

    response = client.get(f"/cockpit/api/runs/{record.run_id}/bundle.zip")

    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("showcase_manifest.json"))
    assert manifest["source_run_id"] == "source-capture-123"


def test_showcase_validation_names_missing_artifact(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    (fixture / "artifacts" / "verification_bundle.json").unlink()

    with pytest.raises(ShowcaseError, match="verification_bundle.json"):
        load_showcase_fixture(fixture)


def test_showcase_validation_rejects_stable_run_id_mismatch(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    manifest_path = fixture / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "a-different-stable-id"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ShowcaseError, match="a-different-stable-id"):
        load_showcase_fixture(fixture)


def test_showcase_validation_requires_source_run_id(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    manifest_path = fixture / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["source_run_id"] = ""
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ShowcaseError, match="source_run_id"):
        load_showcase_fixture(fixture)


def test_showcase_validation_rejects_pack_mismatch(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    manifest_path = fixture / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["pack"]["version"] = "2.0.0"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ShowcaseError, match="capability_pack"):
        load_showcase_fixture(fixture)


@pytest.mark.parametrize(
    ("relative_path", "marker"),
    [
        ("run_record.json", "/Users/"),
        ("manifest.yaml", "TOKEN="),
        ("artifacts/final_report.md", "/private/tmp/"),
    ],
)
def test_showcase_validation_scans_the_entire_fixture_root(
    tmp_path: Path,
    relative_path: str,
    marker: str,
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    path = fixture / relative_path
    if path.name == "run_record.json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repo_path"] = f"{marker}alice/project"
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        unsafe_text = path.read_text(encoding="utf-8") + f"\n# {marker}secret\n"
        path.write_text(unsafe_text, encoding="utf-8")

    with pytest.raises(ShowcaseError, match=re.escape(marker)):
        load_showcase_fixture(fixture)


def test_showcase_validation_rejects_traversal_artifact_name(tmp_path: Path) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    manifest_path = fixture / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["required_artifacts"] = ["../verification_bundle.json"]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ShowcaseError, match=r"\.\./verification_bundle\.json"):
        load_showcase_fixture(fixture)


def test_showcase_script_import_only_uses_requested_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = write_showcase_fixture(tmp_path / "fixture")
    storage = tmp_path / "custom" / "showcase.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "showcase.py",
            "--fixture",
            str(fixture),
            "--storage",
            str(storage),
            "--import-only",
        ],
    )

    assert showcase_script.main() == 0
    assert RunStorage(storage).get("showcase-governed-migration").run_id == (
        "showcase-governed-migration"
    )
    assert "Imported recorded showcase run showcase-governed-migration" in capsys.readouterr().out
