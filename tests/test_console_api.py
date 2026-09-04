"""Console API contract tests (AO-UI-01 backend slice, red-first).

The OpenDesign console screens (docs/design/opendesign-console-v1) read:
runs list with worker/stage/duration/tests-failed columns, run detail, and
an event timeline for replay. The current API serves only the legacy 4-field
runs list. These tests pin the console contract before the UI is wired.

Runs whose record survives only as an artifact-dir run_record.json (storage
was reset at the DSH checkpoint while artifacts were preserved) are still
real runs with real evidence — the console must show them.

Interrupted runs (worker artifacts exist, governed record never written) are
real too: the worker evidence says what it says (completed/failed setup),
and the honest console state for them is "blocked" with a reason — never
"completed" (governed validation never ran) and never hidden.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_api


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr("app.api.settings.llm_provider", "mock")
    return TestClient(create_api(storage_path=tmp_path / "runs.db"))


def _seed_run(client: TestClient, task: str) -> str:
    response = client.post(
        "/runs",
        json={"repo_path": "examples/sample_fastapi_app", "task": task},
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _orphan_artifact(tmp_path: Path, run_id: str, task: str, source_id: str) -> Path:
    """Write a run_record.json artifact for a run that is not in storage."""
    artifact_dir = tmp_path / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    record = json.loads((artifact_dir.parent / source_id / "run_record.json").read_text())
    record["run_id"] = run_id
    record["task"] = task
    (artifact_dir / "run_record.json").write_text(json.dumps(record))
    return artifact_dir


def _interrupted_artifact(tmp_path: Path, run_id: str, task: str) -> Path:
    """Simulate an interrupted run: worker summary + events, no record.

    Mirrors the real dmr flagship artifacts: worker_loop_summary.json with
    worker status completed, worker_prompt.md, openhands_events.jsonl — but
    no run_record.json because the outer graph never reached its write step.
    """
    artifact_dir = tmp_path / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "worker_type": "openhands",
        "status": "completed",
        "exit_code": 0,
        "duration_seconds": 385.9,
        "observable_event_count": 150,
        "model": "openrouter/minimax/minimax-m3:free",
        "termination_reason": "completed",
    }
    (artifact_dir / "worker_loop_summary.json").write_text(json.dumps(summary))
    (artifact_dir / "worker_prompt.md").write_text(f"# Worker Packet\n\n## Task\n{task}\n")
    (artifact_dir / "openhands_events.jsonl").write_text(
        json.dumps(
            {
                "event_type": "ActionEvent",
                "event": {
                    "id": "ev-1",
                    "timestamp": "2026-09-02T15:12:51.326818",
                    "action": {"command": "pwd && ls -la", "kind": "TerminalAction"},
                },
            }
        )
        + "\n"
    )
    return artifact_dir


class TestConsoleRunsList:
    def test_list_includes_console_columns(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        _seed_run(client, "Add request logging middleware")

        response = client.get("/runs")

        assert response.status_code == 200
        row = response.json()[0]
        # Console columns beyond the legacy 4 fields.
        assert row["run_id"]
        assert row["status"] in {"completed", "blocked", "failed"}
        assert "worker" in row
        assert "repo" in row
        assert "duration_seconds" in row
        assert "tests_failed" in row
        assert "started_at" in row
        # Detail-grade columns the runs table renders.
        assert "attempts" in row
        assert "risk_score" in row
        assert "tests_exit" in row
        assert "stages_done" in row

    def test_list_kpis_endpoint_serves_honest_counts(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        _seed_run(client, "One")
        _seed_run(client, "Two")

        response = client.get("/runs/kpis")

        assert response.status_code == 200
        kpis = response.json()
        assert kpis["total"] == 2
        assert kpis["passed"] == 2
        assert kpis["failed"] == 0
        assert kpis["blocked"] == 0
        assert "avg_risk" in kpis


class TestArtifactRecordReconciliation:
    def test_list_includes_runs_only_present_as_artifacts(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        seeded_id = _seed_run(client, "Add request logging middleware")
        _orphan_artifact(tmp_path, "orphan0001", "Orphaned flagship run", seeded_id)

        response = client.get("/runs")

        assert response.status_code == 200
        run_ids = [row["run_id"] for row in response.json()]
        assert "orphan0001" in run_ids
        assert seeded_id in run_ids

    def test_list_orders_runs_most_recent_first_across_sources(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        seeded_id = _seed_run(client, "Add request logging middleware")
        _orphan_artifact(tmp_path, "orphan0002", "Orphaned flagship run", seeded_id)

        rows = client.get("/runs").json()

        # Seeded run completed after the orphan (its record was copied from
        # the seeded run, so ordering must come from completed_at, not luck).
        assert rows[0]["run_id"] == seeded_id
        assert rows[1]["run_id"] == "orphan0002"

    def test_detail_serves_artifact_only_run(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        seeded_id = _seed_run(client, "Add request logging middleware")
        _orphan_artifact(tmp_path, "orphan0003", "Orphaned flagship run", seeded_id)

        response = client.get("/runs/orphan0003")

        assert response.status_code == 200
        assert response.json()["run_id"] == "orphan0003"

    def test_kpis_count_reconciled_runs(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        seeded_id = _seed_run(client, "Add request logging middleware")
        _orphan_artifact(tmp_path, "orphan0004", "Orphaned flagship run", seeded_id)

        kpis = client.get("/runs/kpis").json()

        assert kpis["total"] == 2


class TestInterruptedRuns:
    def test_list_includes_interrupted_run_as_blocked_with_reason(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        _seed_run(client, "Add request logging middleware")
        _interrupted_artifact(tmp_path, "interrupted01", "Orphaned dmr flagship")
        _interrupted_artifact(tmp_path, "interrupted02", "Orphaned pisek trial")

        rows = client.get("/runs").json()
        by_id = {row["run_id"]: row for row in rows}

        row = by_id["interrupted01"]
        # Worker succeeded but governed validation never ran: blocked, never
        # completed (AO-D01-02: execution success != evaluation success).
        assert row["status"] == "blocked"
        assert "governed record" in row["blocked_reason"]
        assert row["worker"] == "openhands"
        assert row["model"] == "openrouter/minimax/minimax-m3:free"
        assert row["duration_seconds"] == 385.9

    def test_interrupted_run_detail_includes_worker_summary_evidence(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        _seed_run(client, "Add request logging middleware")
        _interrupted_artifact(tmp_path, "interrupted03", "Orphaned dmr flagship")

        response = client.get("/runs/interrupted03")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["worker_summary"]["status"] == "completed"
        assert payload["worker_summary"]["observable_event_count"] == 150

    def test_interrupted_run_events_serve_worker_timeline(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        _seed_run(client, "Add request logging middleware")
        _interrupted_artifact(tmp_path, "interrupted04", "Orphaned dmr flagship")

        response = client.get("/runs/interrupted04/events")

        assert response.status_code == 200
        events = response.json()["events"]
        assert events, "worker events must be served for interrupted runs"
        first = events[0]
        assert first["source"] == "worker"
        assert first["kind"] == "T"
        assert first["detail"] == "pwd && ls -la"


class TestRunEvents:
    def test_run_events_returns_timeline(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        run_id = _seed_run(client, "Add request logging middleware")

        response = client.get(f"/runs/{run_id}/events")

        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == run_id
        events = payload["events"]
        assert isinstance(events, list)
        # The graph logs its stage transitions; at least scan + report stages.
        assert len(events) > 0
        first = events[0]
        assert {"seq", "label", "at"} <= set(first)

    def test_run_events_404_on_unknown_run(self, tmp_path: Path, monkeypatch) -> None:
        client = _client(tmp_path, monkeypatch)
        response = client.get("/runs/nonexistent/events")
        assert response.status_code == 404


class TestSpecPreDispatch:
    """AO-UI-01 composer backend: the deterministic pre-dispatch half of the
    governed pipeline, callable from the console — validate the spec, enforce
    environment identity, and (on demand) prove the negative contract against
    a real clone. Dispatch itself stays with the governed CLI (worker secrets
    and long-running dispatch do not belong in the console); the endpoint
    returns the exact command on gate pass."""

    def _buggy_spec(self, base: str, fail_to_pass: list[str]) -> dict:
        return {
            "repo": "example/widgetlib",
            "base_commit": base,
            "problem_statement": "reset(keep_name=True) drops the configured name.",
            "FAIL_TO_PASS": json.dumps(fail_to_pass),
            "PASS_TO_PASS": json.dumps(["test_widget.py::test_reset_clears_name_by_default"]),
        }

    def test_pre_dispatch_rejects_schema_invalid_spec(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        client = _client(tmp_path, monkeypatch)
        response = client.post(
            "/runs/spec/pre-dispatch",
            json={
                "spec": {"repo": "example/widgetlib", "base_commit": "abc"},
                "workspace_root": str(tmp_path / "workspaces"),
            },
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["ok"] is False
        assert payload["stage"] == "invalid"
        assert payload["errors"]

    def test_pre_dispatch_validate_only_skips_gate(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from tests.test_task_spec_solve import _make_remote_with_bug

        client = _client(tmp_path, monkeypatch)
        _, base = _make_remote_with_bug(tmp_path)
        response = client.post(
            "/runs/spec/pre-dispatch",
            json={
                "spec": self._buggy_spec(
                    base, ["test_widget.py::test_reset_keeps_name_when_requested"]
                ),
                "run_gate": False,
                "workspace_root": str(tmp_path / "workspaces"),
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["stage"] == "validated"
        assert payload["gate"] is None
        assert payload["spec"]["fail_to_pass"] == 1

    def test_pre_dispatch_gate_proves_bug_at_base(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The gate runs the real FAIL_TO_PASS probe against a real clone and
        returns evidence (commands + exit codes), not a verdict by assertion."""
        from tests.test_task_spec_solve import _make_remote_with_bug

        client = _client(tmp_path, monkeypatch)
        remote, base = _make_remote_with_bug(tmp_path)
        response = client.post(
            "/runs/spec/pre-dispatch",
            json={
                "spec": self._buggy_spec(
                    base, ["test_widget.py::test_reset_keeps_name_when_requested"]
                ),
                "run_gate": True,
                "clone_url": str(remote),
                "workspace_root": str(tmp_path / "workspaces"),
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["stage"] == "gate_passed"
        gate = payload["gate"]
        assert gate["passed"] is True
        assert gate["command_results"]
        assert all(result["exit_code"] != 0 for result in gate["command_results"])
        assert payload["workspace"]
        assert "agentops issue solve" in payload["dispatch_hint"]

    def test_pre_dispatch_gate_blocks_unreproducible_bug(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Fail-closed: a FAIL_TO_PASS test that passes at base means the bug
        is not reproducible — the console must be able to refuse dispatch."""
        from tests.test_task_spec_solve import _make_remote_with_bug

        client = _client(tmp_path, monkeypatch)
        remote, base = _make_remote_with_bug(tmp_path)
        response = client.post(
            "/runs/spec/pre-dispatch",
            json={
                "spec": self._buggy_spec(
                    base, ["test_widget.py::test_reset_clears_name_by_default"]
                ),
                "run_gate": True,
                "clone_url": str(remote),
                "workspace_root": str(tmp_path / "workspaces"),
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["stage"] == "gate_blocked"
        assert payload["gate"]["passed"] is False
        assert payload["gate"]["reasons"]

    def test_pre_dispatch_blocks_pinned_environment_without_docker(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """AO-D03-02 in the console: a spec pinning an image digest cannot be
        guaranteed by the console's host-side gate — blocked, with the reason."""
        from tests.test_task_spec_solve import _make_remote_with_bug

        client = _client(tmp_path, monkeypatch)
        _, base = _make_remote_with_bug(tmp_path)
        spec = self._buggy_spec(base, ["test_widget.py::test_reset_keeps_name_when_requested"])
        spec["environment"] = {"image_digest": "sha256:" + "ab" * 32}
        response = client.post(
            "/runs/spec/pre-dispatch",
            json={
                "spec": spec,
                "run_gate": False,
                "workspace_root": str(tmp_path / "workspaces"),
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["stage"] == "environment_blocked"
        assert payload["environment"]["pinned"] is True
        assert payload["environment"]["reasons"]
