import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.cockpit import mount_cockpit
from app.core.config import settings
from app.core.graph import run_harness
from app.core.handoff import handoff_document_json, render_handoff_markdown, worker_handoff_from_run
from app.core.llm import LLMClient, build_runtime_llm_client
from app.core.run_artifacts import artifact_dir_for_run
from app.core.storage import RunStorage
from app.schemas.plan import ImplementationPlan
from app.schemas.repo import RepoProfile
from app.schemas.report import FinalReport
from app.schemas.review import ReviewFinding, ReviewReport
from app.schemas.risk import RiskReport
from app.schemas.run import RunRecord
from app.schemas.test import TestRunSummary
from app.schemas.worker_loop import WorkerLoopSummary


class CreateRunRequest(BaseModel):
    repo_path: Path
    task: str
    test_commands: list[str] | None = None
    worker_command: str | None = None
    worker_timeout_seconds: int = 300
    allow_dirty: bool = False


class SpecPreDispatchRequest(BaseModel):
    """Composer request: a raw SWE-bench-style spec plus pre-dispatch options.

    ``run_gate`` clones at base_commit and proves the negative contract —
    real work, so the console triggers it deliberately, not on every keystroke.
    """

    spec: dict
    run_gate: bool = False
    clone_url: str | None = None
    workspace_root: Path | None = None


_WORKER_EVENT_KINDS = {
    "SystemPromptEvent": "S",
    "MessageEvent": "M",
    "ActionEvent": "T",
    "ObservationEvent": "O",
    "Condensation": "C",
    "AgentErrorEvent": "E",
}


def _worker_event(seq: int, payload: dict) -> dict[str, object]:
    """Normalize one OpenHands JSONL event for the console replay timeline."""
    event_type = payload.get("event_type", "Unknown")
    kind = _WORKER_EVENT_KINDS.get(event_type, "?")
    event = payload.get("event") or {}
    timestamp = event.get("timestamp") or payload.get("timestamp")
    detail = ""
    if isinstance(event, dict):
        action = event.get("action")
        if isinstance(action, dict) and action:
            command = action.get("command")
            if isinstance(command, str):
                detail = command
            else:
                detail = action.get("kind") or action.get("path") or ""
        elif event.get("observation"):
            detail = "observation returned"
        elif event.get("llm_message"):
            detail = "worker message composed (task + constraints)"
        elif event.get("system_prompt"):
            detail = "system prompt set (harness constraints)"
    if not detail:
        detail = event_type
    return {
        "seq": seq,
        "kind": kind,
        "label": event_type,
        "detail": detail,
        "at": timestamp,
        "source": "worker",
    }


def _get_record(storage_path: Path, run_id: str) -> "RunRecord":
    """Read one run: storage first, then artifact dir, then interrupted runs."""
    try:
        return RunStorage(storage_path).get(run_id)
    except KeyError:
        artifact_dir = artifact_dir_for_run(storage_path, run_id)
        record_path = artifact_dir / "run_record.json"
        if record_path.is_file():
            try:
                return RunRecord.model_validate_json(
                    record_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise KeyError(f"Run not found: {run_id}") from exc
        summary_path = artifact_dir / "worker_loop_summary.json"
        if summary_path.is_file():
            record = _interrupted_run_record(artifact_dir, summary_path)
            if record is not None:
                _INTERRUPTED_SUMMARIES[run_id] = _load_worker_summary(summary_path)
                return record
        raise


def _reconciled_records(storage_path: Path, limit: int) -> list["RunRecord"]:
    """Merge stored records with artifact-only and interrupted runs.

    The checkpoint reset run storage while preserving artifact directories
    (including run_record.json). Those runs are real runs with real evidence;
    hiding them would be dishonest. Storage wins on conflict; artifact-only
    records fill the gap.

    A dir with worker artifacts but no run_record.json is an interrupted run:
    the worker executed but the governed graph never wrote its record. The
    honest state is "blocked" (governed validation never ran), with the worker
    summary served as evidence — never "completed", never hidden. Reconstructed
    records are marked source="interrupted" so the console can badge them.
    Most recent first.
    """
    storage = RunStorage(storage_path)
    stored = storage.list(limit=limit)
    artifact_root = artifact_dir_for_run(storage_path, "*").parent
    if not artifact_root.is_dir():
        return stored
    stored_ids = {record.run_id for record in stored}
    reconciled: list[RunRecord] = list(stored)
    for record_dir in sorted(artifact_root.iterdir()):
        if not record_dir.is_dir():
            continue
        record_path = record_dir / "run_record.json"
        if record_path.is_file():
            try:
                record = RunRecord.model_validate_json(
                    record_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if record.run_id not in stored_ids:
                reconciled.append(record)
            continue
        summary_path = record_dir / "worker_loop_summary.json"
        if summary_path.is_file():
            reconstructed = _interrupted_run_record(record_dir, summary_path)
            if reconstructed is not None:
                _INTERRUPTED_SUMMARIES[record_dir.name] = _load_worker_summary(
                    summary_path
                )
                reconciled.append(reconstructed)
    reconciled.sort(key=lambda record: record.completed_at, reverse=True)
    return reconciled[:limit]


# Worker summaries for interrupted runs (no governed record): run_id -> summary.
# Populated during reconciliation; read by the list/detail/events endpoints.
_INTERRUPTED_SUMMARIES: dict[str, "WorkerLoopSummary | None"] = {}


def _load_worker_summary(summary_path: Path) -> "WorkerLoopSummary | None":
    try:
        return WorkerLoopSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _is_interrupted_run(storage_path: Path, run_id: str) -> bool:
    artifact_dir = artifact_dir_for_run(storage_path, run_id)
    return (
        not (artifact_dir / "run_record.json").is_file()
        and (artifact_dir / "worker_loop_summary.json").is_file()
    )


def _interrupted_run_record(record_dir: Path, summary_path: Path) -> "RunRecord | None":
    """Build an honest blocked record for an interrupted run from artifacts.

    Evidence carried: worker summary (status/model/duration/events), the task
    parsed from worker_prompt.md. Status is "blocked" regardless of worker
    status — governed evaluation never ran (AO-D01-02 separation).
    """
    try:
        summary = WorkerLoopSummary.model_validate_json(
            summary_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    prompt_path = record_dir / "worker_prompt.md"
    task = f"interrupted run in {record_dir.name}"
    if prompt_path.is_file():
        match = re.search(
            r"^## Task\n(.+)$", prompt_path.read_text(encoding="utf-8"), re.MULTILINE
        )
        if match:
            task = match.group(1).strip()
    started_at = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=UTC)
    note = (
        "Interrupted run: governed validation never ran; worker artifacts only. "
        f"Worker reported status={summary.status}."
    )
    record = RunRecord(
        run_id=record_dir.name,
        task=task,
        repo_path="",
        repo_profile=RepoProfile(repo_path="unknown (interrupted run)"),
        plan=ImplementationPlan(
            task=task,
            summary="Interrupted run: governed pipeline never completed.",
            steps=[],
            acceptance_criteria=[],
            tests_to_run=[],
        ),
        test_results=TestRunSummary(commands=[]),
        review_report=ReviewReport(
            summary=note,
            findings=[
                ReviewFinding(
                    severity="info",
                    title="Interrupted run",
                    description=note,
                    recommendation="Rerun the task through the governed pipeline.",
                )
            ],
        ),
        risk_report=RiskReport(
            risk_score=0,
            risk_level="low",
            factors=["interrupted run: risk never evaluated by governed pipeline"],
        ),
        final_report=FinalReport(
            title=f"Interrupted run {record_dir.name}",
            markdown=f"# Interrupted run {record_dir.name}\n\n{note}\n",
        ),
        status="blocked",
        execution_logs=[
            "interrupted_run:worker_artifacts_present",
            f"interrupted_run:worker_status={summary.status}",
            f"interrupted_run:worker_model={summary.model or 'unknown'}",
            f"interrupted_run:worker_duration={summary.duration_seconds}",
            f"interrupted_run:worker_events={summary.observable_event_count}",
            "interrupted_run:governed_record_missing",
        ],
        started_at=started_at,
        completed_at=started_at,
    )
    return record


def create_api(storage_path: Path | None = None, llm_client: LLMClient | None = None) -> FastAPI:
    api = FastAPI(title="AgentOps Harness API")
    selected_storage = storage_path or settings.run_storage
    selected_llm_client = (
        llm_client if llm_client is not None else build_runtime_llm_client(settings)
    )

    @api.post("/runs", status_code=201)
    def create_run(request: CreateRunRequest) -> dict[str, str]:
        record = run_harness(
            repo_path=request.repo_path,
            task=request.task,
            storage_path=selected_storage,
            llm_client=selected_llm_client,
            test_commands=request.test_commands,
            worker_command=request.worker_command,
            worker_timeout_seconds=request.worker_timeout_seconds,
            allow_dirty=request.allow_dirty,
        )
        return {"run_id": record.run_id, "status": record.status}

    @api.get("/runs")
    def list_runs(limit: int = 20) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record in _reconciled_records(selected_storage, limit):
            summary = _INTERRUPTED_SUMMARIES.get(record.run_id)
            interrupted = summary is not None and record.status == "blocked"
            row: dict[str, object] = {
                "run_id": record.run_id,
                "task": record.task,
                "status": record.status,
                "risk_level": record.risk_report.risk_level,
                # Console columns (AO-UI-01): worker, repo, timing, tests.
                "worker": (
                    summary.worker_type
                    if interrupted
                    else record.edit_result.worker_type
                    if record.edit_result is not None
                    else "scripted"
                ),
                "repo": Path(record.repo_path).name,
                "duration_seconds": (
                    summary.duration_seconds
                    if interrupted
                    else round(
                        (record.completed_at - record.started_at).total_seconds(),
                        ndigits=1,
                    )
                ),
                "tests_failed": sum(
                    1
                    for result in record.test_results.commands
                    if result.exit_code != 0
                ),
                "started_at": record.started_at.isoformat(),
                # Detail-grade columns for the runs table (AO-UI-01).
                "attempts": record.attempts,
                "risk_score": record.risk_report.risk_score,
                "tests_exit": (
                    record.test_results.commands[-1].exit_code
                    if record.test_results.commands
                    else None
                ),
                "stages_done": sum(
                    1 for entry in record.execution_logs if entry.endswith(":complete")
                ),
            }
            if interrupted and summary is not None:
                row["source"] = "interrupted"
                row["model"] = summary.model
                row["blocked_reason"] = (
                    "worker finished but governed record never written — "
                    "governed validation did not run"
                )
            rows.append(row)
        return rows

    @api.get("/runs/kpis")
    def get_kpis(limit: int = 100) -> dict[str, float]:
        records = _reconciled_records(selected_storage, limit)
        total = len(records)
        risk_scores = [record.risk_report.risk_score for record in records]
        return {
            "total": total,
            "passed": sum(1 for record in records if record.status == "completed"),
            "failed": sum(1 for record in records if record.status == "failed"),
            "blocked": sum(1 for record in records if record.status == "blocked"),
            "avg_risk": round(sum(risk_scores) / total, ndigits=1) if risk_scores else 0.0,
        }

    @api.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            record = _get_record(selected_storage, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = record.model_dump(mode="json")
        summary = _INTERRUPTED_SUMMARIES.get(run_id)
        if summary is not None:
            payload["worker_summary"] = summary.model_dump(mode="json")
            payload["source"] = "interrupted"
        return payload

    @api.get("/runs/{run_id}/report")
    def get_report(run_id: str) -> dict[str, str]:
        try:
            record = _get_record(selected_storage, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run_id": record.run_id, "report": record.final_report.markdown}

    @api.get("/runs/{run_id}/logs")
    def get_logs(run_id: str) -> dict[str, str | list[str]]:
        try:
            record = _get_record(selected_storage, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run_id": record.run_id, "logs": record.execution_logs}

    @api.get("/runs/{run_id}/events")
    def get_events(run_id: str) -> dict[str, object]:
        try:
            record = _get_record(selected_storage, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        events: list[dict[str, object]] = []
        # The harness's own stage transitions are the timeline backbone: every
        # run has them (mock, scripted, and worker modes alike). Interrupted
        # runs have no real stage transitions — their execution_logs are
        # synthetic tombstone notes (served via /logs), not a timeline; their
        # honest timeline is the worker's own event stream below.
        interrupted = run_id in _INTERRUPTED_SUMMARIES
        if not interrupted:
            for seq, entry in enumerate(record.execution_logs):
                label, _, detail = entry.partition(":")
                events.append(
                    {"seq": seq, "label": label, "detail": detail.lstrip(":"), "at": seq}
                )

        # Worker events (openhands_events.jsonl) extend the timeline when the
        # artifact exists; kind mapping mirrors the console's replay legend.
        artifact_dir = artifact_dir_for_run(selected_storage, run_id)
        events_path = artifact_dir / "openhands_events.jsonl"
        if events_path.is_file():
            base = len(events)
            for offset, raw in enumerate(events_path.read_text().splitlines()):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except ValueError:
                    continue
                events.append(_worker_event(base + offset, payload))
        return {"run_id": run_id, "events": events}

    @api.get("/runs/{run_id}/handoff", response_model=None)
    def get_handoff(
        run_id: str,
        response_format: Literal["markdown", "json"] = Query(
            default="markdown",
            alias="format",
        ),
    ) -> PlainTextResponse | dict:
        try:
            record = _get_record(selected_storage, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        packet = worker_handoff_from_run(record)
        if response_format == "json":
            return handoff_document_json(packet)
        return PlainTextResponse(
            render_handoff_markdown(packet),
            media_type="text/markdown; charset=utf-8",
        )

    @api.post("/runs/spec/pre-dispatch")
    def pre_dispatch_spec(request: SpecPreDispatchRequest) -> dict:
        """The deterministic pre-dispatch half of a governed spec run (AO-UI-01).

        Validate the spec, enforce environment identity, and — on demand —
        prove the negative contract against a real clone at base_commit.
        Dispatch itself stays with the governed CLI: the endpoint returns the
        exact command once the gate opens. Worker secrets and long-running
        dispatch do not belong in the console.
        """
        from pydantic import ValidationError

        from app.core.environment_guard import (
            docker_image_digest,
            verify_environment_identity,
        )
        from app.schemas.task_spec import SweTaskSpec

        payload: dict[str, object] = {
            "ok": False,
            "stage": "invalid",
            "spec": None,
            "environment": None,
            "gate": None,
            "workspace": None,
            "dispatch_hint": None,
            "errors": [],
        }

        try:
            task_spec = SweTaskSpec.from_swebench_instance(request.spec)
        except (KeyError, ValueError, ValidationError) as exc:
            payload["errors"] = [str(exc)]
            return JSONResponse(status_code=422, content=payload)

        payload["spec"] = {
            "repo": task_spec.repo,
            "base_commit": task_spec.base_commit,
            "fail_to_pass": len(task_spec.fail_to_pass),
            "pass_to_pass": len(task_spec.pass_to_pass),
        }

        # The console gates on the host; a pinned image identity cannot be
        # guaranteed there (AO-D03-02) — fail closed with the reason.
        env = verify_environment_identity(
            task_spec.environment,
            workspace_kind="local",
            image_ref=None,
            resolve_image_digest=docker_image_digest,
        )
        payload["environment"] = {"pinned": env.pinned, "ok": env.ok, "reasons": env.reasons}
        if not env.ok:
            payload["stage"] = "environment_blocked"
            payload["errors"] = env.reasons
            return payload

        if not request.run_gate:
            payload.update(ok=True, stage="validated")
            return payload

        from app.core.issues import prepare_issue_workspace, spec_issue_stub
        from app.core.task_spec_gate import evaluate_negative_contract

        workspace_root = request.workspace_root or Path(".agentops/issues")
        try:
            repo_path, _branch = prepare_issue_workspace(
                spec_issue_stub(task_spec),
                workspace_root,
                ref=task_spec.base_commit,
                clone_url=request.clone_url,
            )
            gate = evaluate_negative_contract(task_spec, repo_path)
        except Exception as exc:  # noqa: BLE001 — infra failure is inconclusive, never a pass
            payload["stage"] = "error"
            payload["errors"] = [f"Pre-dispatch could not complete: {exc}"]
            return payload

        payload["gate"] = {
            "passed": gate.passed,
            "reasons": gate.reasons,
            "command_results": [
                {
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "output_tail": result.output_tail,
                }
                for result in gate.command_results
            ],
        }
        payload["workspace"] = str(repo_path)
        if gate.passed:
            owner, _, name = task_spec.repo.partition("/")
            number = int(task_spec.base_commit[:8], 16) % 900000
            payload.update(
                ok=True,
                stage="gate_passed",
                dispatch_hint=(
                    "agentops issue solve --task-spec <spec.json>"
                    f" --owner {owner or 'spec'} --repo {name or owner}"
                    f" --number {number} --worker openhands"
                ),
            )
            return payload
        payload["stage"] = "gate_blocked"
        payload["errors"] = gate.reasons
        return payload

    mount_cockpit(api, selected_storage)
    _mount_console(api)
    return api


def _mount_console(api: FastAPI) -> None:
    """Serve the OpenDesign operator console screens at /console.

    The screens are design prototypes (docs/design/opendesign-console-v1)
    wired to live API data by console-data.js. Mounted read-only; the runs
    they show come from the same storage as every other surface.
    """
    console_dir = Path(__file__).resolve().parents[1] / "docs" / "design" / "opendesign-console-v1"
    if console_dir.is_dir():
        api.mount(
            "/console",
            StaticFiles(directory=console_dir, html=True),
            name="console",
        )


api = create_api()
