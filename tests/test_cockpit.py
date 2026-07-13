import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_api
from app.cockpit.artifacts import CockpitReader
from app.core.run_artifacts import RunArtifactWriter, artifact_dir_for_run
from app.core.storage import RunStorage
from app.schemas.pack import CapabilityPackProvenance
from tests.helpers_runrecord import minimal_run_record

_OBSERVE_LOGS = [
    "scan_repo:start",
    "scan_repo:complete",
    "create_plan:complete",
    "prepare_workspace:complete",
    "pre_dispatch:observe",
    "collect_diff:complete",
    "enforce_permissions:skip",
    "run_tests:complete",
    "review_diff:complete",
    "assess_risk:complete",
    "audit_conflicts:complete",
]


def _saved_reader(tmp_path: Path) -> CockpitReader:
    record = minimal_run_record()
    record.run_id = "r1"
    record.task = "Add logging"
    record.execution_logs = list(_OBSERVE_LOGS)
    storage = tmp_path / "runs.jsonl"
    RunStorage(storage).save(record)
    return CockpitReader(storage)


def test_reader_summary_stats_and_phases(tmp_path: Path) -> None:
    reader = _saved_reader(tmp_path)

    listing = reader.list_summaries()
    assert listing["stats"] == {"total": 1, "pass_rate": 100, "avg_risk": 0, "running": 0}
    summary = listing["runs"][0]
    assert summary["task"] == "Add logging"
    assert summary["worker"] == "observe"
    assert summary["product_verdict"] == "not_evaluated"

    detail = reader.detail("r1")
    statuses = {p["name"]: p["status"] for p in detail["phases"]}
    assert statuses == {
        "plan": "done",
        "worker": "done",
        "enforce": "skipped",
        "tests": "done",
        "review": "done",
    }
    assert detail["verification"] == {
        "accepted": True,
        "overall_confidence": "low",
    }


def test_old_run_without_pack_remains_readable(tmp_path: Path) -> None:
    payload = minimal_run_record().model_dump(mode="json", exclude={"capability_pack"})
    storage = tmp_path / "runs.jsonl"
    storage.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    detail = CockpitReader(storage).detail("testrun")

    assert detail["record"]["capability_pack"] is None
    assert detail["summary"]["capability_pack"] is None


def test_run_artifacts_include_capability_pack_json(tmp_path: Path) -> None:
    record = minimal_run_record()
    record.capability_pack = CapabilityPackProvenance(
        name="demo",
        domain="testing",
        version="1.0.0",
        description="demo",
        skills=["playbook.md"],
        resolved_tools=["terminal"],
        hooks=[],
        manifest_sha256="b" * 64,
    )
    RunArtifactWriter().write(record, tmp_path / "runs.db")
    payload = json.loads(
        (
            artifact_dir_for_run(tmp_path / "runs.db", record.run_id)
            / "capability_pack.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["resolved_tools"] == ["terminal"]


def test_inner_events_skips_partial_json_line(tmp_path: Path) -> None:
    # A mid-write trailing line must be skipped, not raise (the cockpit polls the
    # file while the worker appends to it).
    storage = tmp_path / "runs.jsonl"
    run_dir = artifact_dir_for_run(storage, "r1")
    run_dir.mkdir(parents=True)
    (run_dir / "openhands_events.jsonl").write_text(
        '{"event_type": "ActionEvent", "event": {"tool_name": "terminal"}}\n'
        '{"event_type": "Obs", "event": {"observ',  # partial, malformed
        encoding="utf-8",
    )
    events = CockpitReader(storage).inner_events("r1")
    assert len(events) == 1


def test_cockpit_worker_stream_emits_existing_inner_events(tmp_path: Path, monkeypatch) -> None:
    # Regression: the worker stream must emit events that already exist in the log
    # (the prior logic skipped the tail path once any event was present).
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    storage = tmp_path / "runs.db"
    client = TestClient(create_api(storage_path=storage))
    run_id = client.post(
        "/runs",
        json={"repo_path": "examples/sample_fastapi_app", "task": "Inner stream"},
    ).json()["run_id"]
    run_dir = artifact_dir_for_run(storage, run_id)
    (run_dir / "openhands_events.jsonl").write_text(
        '{"event_type": "ActionEvent", "event": {"tool_name": "terminal", '
        '"action": {"command": "pytest -q"}}}\n'
        '{"event_type": "ObservationEvent", "event": {"observation": {"content": "ok"}}}\n',
        encoding="utf-8",
    )

    seen = 0
    with client.stream("GET", f"/cockpit/api/runs/{run_id}/worker/stream") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line == "event: event":
                seen += 1
            if seen == 2:
                break
    assert seen == 2


def test_reader_worker_view_absent_for_observe_runs(tmp_path: Path) -> None:
    reader = _saved_reader(tmp_path)
    worker = reader.worker_view("r1")
    assert worker["present"] is False
    assert worker["count"] == 0


def test_reader_worker_view_parses_inner_loop(tmp_path: Path) -> None:
    from app.core.run_artifacts import artifact_dir_for_run
    from app.core.workers.openhands_artifacts import write_worker_events, write_worker_summary
    from app.schemas.worker_loop import WorkerLoopSummary

    reader = _saved_reader(tmp_path)
    run_dir = artifact_dir_for_run(tmp_path / "runs.jsonl", "r1")
    write_worker_summary(run_dir, WorkerLoopSummary(status="completed", model="anthropic/x"))
    write_worker_events(run_dir, [
        {"event_type": "ActionEvent",
         "event": {"source": "agent", "tool_name": "terminal", "action": {"command": "pytest -q"}}},
        {"event_type": "ObservationEvent", "event": {"observation": {"content": "3 passed"}}},
    ])

    worker = reader.worker_view("r1")
    assert worker["present"] is True
    assert worker["count"] == 2
    assert worker["summary"]["model"] == "anthropic/x"
    first = worker["events"][0]
    assert first["kind"] == "action"
    assert first["tool"] == "terminal"
    assert first["summary"] == "pytest -q"
    assert worker["events"][1]["kind"] == "observation"


def test_reader_trajectory_falls_back_to_execution_logs(tmp_path: Path) -> None:
    reader = _saved_reader(tmp_path)
    trajectory = reader.trajectory("r1")
    assert trajectory[0] == {
        "index": 0,
        "node": "scan_repo",
        "phase": "start",
        "raw": "scan_repo:start",
        "tone": "active",
    }
    assert trajectory[1]["tone"] == "ok"  # scan_repo:complete


def test_cockpit_api_lists_and_inspects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=tmp_path / "runs.db"))

    run_id = client.post(
        "/runs",
        json={"repo_path": "examples/sample_fastapi_app", "task": "Add a /health endpoint"},
    ).json()["run_id"]

    listing = client.get("/cockpit/api/runs").json()
    assert listing["stats"]["total"] == 1
    assert any(r["run_id"] == run_id for r in listing["runs"])

    detail = client.get(f"/cockpit/api/runs/{run_id}").json()
    assert len(detail["phases"]) == 5
    assert detail["trajectory"]
    assert detail["live"] is False
    assert detail["record"]["run_id"] == run_id


def test_cockpit_api_returns_404_for_missing_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=tmp_path / "runs.db"))
    assert client.get("/cockpit/api/runs/missing").status_code == 404


def test_cockpit_serves_raw_artifacts_and_blocks_traversal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=tmp_path / "runs.db"))
    run_id = client.post(
        "/runs",
        json={"repo_path": "examples/sample_fastapi_app", "task": "Inspect artifacts"},
    ).json()["run_id"]

    detail = client.get(f"/cockpit/api/runs/{run_id}").json()
    names = {a["name"] for a in detail["artifacts"]}
    assert "run_record.json" in names
    assert "final_report.md" in names

    raw = client.get(f"/cockpit/api/runs/{run_id}/artifacts/risk_report.json")
    assert raw.status_code == 200
    assert "risk_score" in raw.text

    # a name that is not a file in the run dir must 404 (no path traversal)
    missing = client.get(f"/cockpit/api/runs/{run_id}/artifacts/does_not_exist.json")
    assert missing.status_code == 404

    bundle = client.get(f"/cockpit/api/runs/{run_id}/bundle.zip")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert bundle.content[:2] == b"PK"


def test_cockpit_stream_emits_sse_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    client = TestClient(create_api(storage_path=tmp_path / "runs.db"))
    run_id = client.post(
        "/runs",
        json={"repo_path": "examples/sample_fastapi_app", "task": "Stream me"},
    ).json()["run_id"]

    seen_open = seen_event = False
    with client.stream("GET", f"/cockpit/api/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            seen_open = seen_open or line == "event: open"
            seen_event = seen_event or line == "event: event"
            if seen_open and seen_event:
                break
    assert seen_open and seen_event
