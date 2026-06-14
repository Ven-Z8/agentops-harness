"""Read run records + artifact bundles into cockpit-shaped payloads.

Everything here is deterministic projection over data the harness already owns:
the ``RunRecord`` (via ``RunStorage``) and the per-run ``trace.jsonl`` written by
``RunArtifactWriter``. No LLM calls, no new persistence.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.run_artifacts import artifact_dir_for_run
from app.core.storage import RunStorage
from app.schemas.run import RunRecord

# The five macro-phases the governance pipeline collapses to, and the LangGraph
# node names whose lifecycle events feed each one. Order is display order.
PIPELINE_PHASES: list[tuple[str, tuple[str, ...]]] = [
    ("plan", ("scan_repo", "repo_graph", "goal_model", "recall_experience",
              "create_plan", "prepare_workspace", "pre_dispatch")),
    ("worker", ("run_external_worker", "collect_diff")),
    ("enforce", ("enforce_permissions",)),
    ("tests", ("run_tests", "check_convergence")),
    ("review", ("build_changed_subgraph", "review_diff", "assess_risk",
                "classify_permissions", "write_report", "check_report_quality",
                "check_evidence", "build_product_review", "assemble_verification",
                "audit_conflicts")),
]

# Per-run live event log appended by the openhands worker during an in-flight run.
LIVE_EVENT_FILE = "openhands_events.jsonl"
WORKER_SUMMARY_FILE = "worker_loop_summary.json"
WORKER_SCORECARD_FILE = "worker_scorecard.json"


class CockpitReader:
    """Projects stored runs + artifacts into cockpit JSON payloads."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = storage_path
        self._storage = RunStorage(storage_path)

    # ── collection-level ────────────────────────────────────────────────
    def stats(self, records: list[RunRecord] | None = None) -> dict:
        records = records if records is not None else self._storage.list(limit=500)
        total = len(records)
        completed = sum(1 for r in records if r.status == "completed")
        running = sum(1 for r in records if r.status not in {"completed", "blocked", "failed"})
        avg_risk = round(sum(r.risk_report.risk_score for r in records) / total) if total else 0
        return {
            "total": total,
            "pass_rate": round(100 * completed / total) if total else 0,
            "avg_risk": avg_risk,
            "running": running,
        }

    def list_summaries(self, limit: int = 50) -> dict:
        records = self._storage.list(limit=limit)
        return {
            "stats": self.stats(records),
            "runs": [self.summarize(r) for r in records],
        }

    # ── single run ──────────────────────────────────────────────────────
    def summarize(self, record: RunRecord) -> dict:
        commands = record.test_results.commands
        passed = sum(1 for c in commands if c.exit_code == 0)
        return {
            "run_id": record.run_id,
            "task": record.task,
            "repo_path": record.repo_path,
            "status": record.status,
            "worker": _worker_label(record),
            "risk_score": record.risk_report.risk_score,
            "risk_level": record.risk_report.risk_level,
            "blocked": record.risk_report.blocked or record.permission_report.blocked,
            "permission_tier": record.permission_report.highest_tier,
            "changed_files": len(record.changed_files),
            "tests_passed": passed,
            "tests_total": len(commands),
            "evidence_flags": record.evidence_report.unsupported_claim_count,
            "evidence_grounded": record.evidence_report.grounded,
            "product_verdict": record.product_review.overall_verdict,
            "attempts": record.attempts,
            "converged": record.converged,
            "started_at": record.started_at.isoformat(),
            "completed_at": record.completed_at.isoformat(),
            "duration_seconds": _duration(record.started_at, record.completed_at),
        }

    def detail(self, run_id: str) -> dict:
        """Full inspector payload: record + derived phases + trajectory."""
        record = self._storage.get(run_id)
        return {
            "summary": self.summarize(record),
            "record": record.model_dump(mode="json"),
            "phases": self.phases(record),
            "trajectory": self.trajectory(run_id, record),
            "live": self.live_event_path(run_id).exists(),
            "artifacts": self.artifact_files(run_id),
            "worker": self.worker_view(run_id),
        }

    # ── derived views ───────────────────────────────────────────────────
    def trajectory(self, run_id: str, record: RunRecord | None = None) -> list[dict]:
        """Parsed governance/loop events, newest semantics preserved in order."""
        record = record if record is not None else self._storage.get(run_id)
        events = self._read_trace(run_id) or [
            {"index": i, "event": e} for i, e in enumerate(record.execution_logs)
        ]
        parsed = []
        for raw in events:
            event = raw.get("event", "")
            node, _, phase = event.partition(":")
            parsed.append({
                "index": raw.get("index", len(parsed)),
                "node": node,
                "phase": phase or "event",
                "raw": event,
                "tone": _event_tone(phase),
            })
        return parsed

    def phases(self, record: RunRecord) -> list[dict]:
        """Map node lifecycle events onto the five macro-phases with a status."""
        seen: dict[str, set[str]] = {}
        for entry in record.execution_logs:
            node, _, phase = entry.partition(":")
            seen.setdefault(node, set()).add(phase)
        result = []
        for name, nodes in PIPELINE_PHASES:
            phases_hit = {p for n in nodes for p in seen.get(n, set())}
            if "complete" in phases_hit:
                status = "done"
            elif "start" in phases_hit:
                status = "active"
            elif phases_hit & {"skip", "observe", "absent", "miss"}:
                status = "skipped"
            else:
                status = "pending"
            result.append({"name": name, "status": status})
        return result

    def live_event_path(self, run_id: str) -> Path:
        return artifact_dir_for_run(self.storage_path, run_id) / LIVE_EVENT_FILE

    # ── raw artifact files ──────────────────────────────────────────────
    def artifact_files(self, run_id: str) -> list[dict]:
        """List the literal files the backend wrote for this run."""
        run_dir = artifact_dir_for_run(self.storage_path, run_id)
        if not run_dir.is_dir():
            return []
        files = [p for p in run_dir.iterdir() if p.is_file()]
        return [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(files, key=lambda p: p.name)
        ]

    def artifact_text(self, run_id: str, name: str, max_bytes: int = 400_000) -> str:
        """Return the raw text of one artifact file, guarded against traversal."""
        run_dir = artifact_dir_for_run(self.storage_path, run_id)
        allowed = {p.name for p in run_dir.iterdir() if p.is_file()} if run_dir.is_dir() else set()
        if name not in allowed:
            raise KeyError(f"Artifact not found: {name}")
        data = (run_dir / name).read_text(encoding="utf-8", errors="replace")
        if len(data) > max_bytes:
            return data[:max_bytes] + f"\n… (truncated at {max_bytes} bytes)"
        return data

    # ── inner OpenHands worker loop ─────────────────────────────────────
    def worker_view(self, run_id: str) -> dict:
        """The inner agent loop: model/tools machinery + tool-call trajectory.

        Sourced from the openhands worker artifacts (``worker_loop_summary.json``,
        ``worker_scorecard.json``, ``openhands_events.jsonl``). Empty when the run
        did not use ``--worker-type openhands`` — observe/CLI runs have no inner loop.
        """
        run_dir = artifact_dir_for_run(self.storage_path, run_id)
        summary = self._read_json(run_dir / WORKER_SUMMARY_FILE)
        scorecard = self._read_json(run_dir / WORKER_SCORECARD_FILE)
        events = self.inner_events(run_id)
        return {
            "present": bool(events or summary),
            "live": (run_dir / LIVE_EVENT_FILE).exists(),
            "summary": summary,
            "scorecard": scorecard,
            "events": events,
            "count": len(events),
        }

    def inner_events(self, run_id: str) -> list[dict]:
        path = artifact_dir_for_run(self.storage_path, run_id) / LIVE_EVENT_FILE
        if not path.exists():
            return []
        events = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                events.append(_normalize_inner_event(i, json.loads(line)))
        return events

    # ── internals ───────────────────────────────────────────────────────
    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_trace(self, run_id: str) -> list[dict]:
        trace = artifact_dir_for_run(self.storage_path, run_id) / "trace.jsonl"
        if not trace.exists():
            return []
        out = []
        for line in trace.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out


def _worker_label(record: RunRecord) -> str:
    edit = record.edit_result
    if not edit:
        return "observe"
    return edit.worker_type or edit.mode


def _duration(start: datetime, end: datetime) -> float:
    return round(max((end - start).total_seconds(), 0.0), 2)


def _event_tone(phase: str) -> str:
    if phase == "complete":
        return "ok"
    if phase == "start":
        return "active"
    if phase in {"skip", "observe", "absent", "miss"}:
        return "muted"
    return "info"


# Map OpenHands SDK event class names onto a small set of display kinds. Matched
# as substrings so SDK-version renames (ActionEvent / AgentActionEvent / …) still land.
def _inner_kind(event_type: str) -> str:
    t = event_type.lower()
    if "action" in t:
        return "action"
    if "observation" in t:
        return "observation"
    if "message" in t:
        return "message"
    if "error" in t or "exception" in t:
        return "error"
    if "state" in t or "finish" in t:
        return "state"
    return "other"


def _flatten_content(value: object) -> str:
    """Reduce an OpenHands content value (str / block dict / list of blocks) to text."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _flatten_content(value.get("content") or value.get("text") or "")
    if isinstance(value, list):
        parts = [
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in value
        ]
        return " ".join(p for p in parts if p)
    return ""


def _normalize_inner_event(index: int, obj: dict) -> dict:
    """Project one ``{event_type, event}`` line into a readable inner-loop row.

    Defensive: OpenHands event field names shift across SDK versions, so we probe
    a list of candidate keys and fall back to a compact snippet rather than break.
    """
    event_type = obj.get("event_type", "Event")
    ev = obj.get("event", {})
    if not isinstance(ev, dict):
        return {"index": index, "type": event_type, "kind": "other",
                "tool": "", "source": "", "summary": str(ev)[:400]}

    source = ev.get("source") or ev.get("role") or ""
    tool = ev.get("tool_name") or ev.get("tool") or ""
    summary = ""

    action = ev.get("action")
    if isinstance(action, dict):
        tool = tool or action.get("tool") or action.get("kind") or action.get("name") or ""
        command = action.get("command") or action.get("code") or ""
        path = action.get("path") or ""
        summary = " ".join(x for x in (command, path) if x) \
            or _flatten_content(action.get("content") or action.get("thought"))

    obs = ev.get("observation")
    if isinstance(obs, dict):
        summary = summary or _flatten_content(
            obs.get("content") or obs.get("output") or obs.get("message")
        )

    if not summary:
        summary = _flatten_content(
            ev.get("message") or ev.get("llm_message") or ev.get("content") or ev.get("thought")
        )

    text = str(summary).strip()
    return {
        "index": index,
        "type": event_type,
        "kind": _inner_kind(event_type),
        "tool": str(tool),
        "source": str(source),
        "summary": text[:300],
        "full": text[:6000],
    }
