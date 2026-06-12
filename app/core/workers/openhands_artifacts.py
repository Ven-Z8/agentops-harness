from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.edit import ExternalEditResult
from app.schemas.worker_loop import WorkerArtifactPaths, WorkerLoopSummary, WorkerScorecard


def _ensure_run_dir(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, value: Any) -> Path:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_worker_prompt(run_dir: Path, prompt: str) -> Path:
    return _write_text(_ensure_run_dir(run_dir) / "worker_prompt.md", prompt.rstrip() + "\n")


def write_worker_logs(run_dir: Path, stdout: str, stderr: str) -> tuple[Path, Path]:
    root = _ensure_run_dir(run_dir)
    return (
        _write_text(root / "worker_stdout.log", stdout),
        _write_text(root / "worker_stderr.log", stderr),
    )


def write_worker_summary(run_dir: Path, summary: WorkerLoopSummary) -> Path:
    return _write_json(_ensure_run_dir(run_dir) / "worker_loop_summary.json", summary)


def write_worker_result(run_dir: Path, result: ExternalEditResult) -> Path:
    return _write_json(_ensure_run_dir(run_dir) / "worker_result.json", result)


def write_worker_events(run_dir: Path, events: list[dict[str, Any]]) -> Path | None:
    if not events:
        return None
    path = _ensure_run_dir(run_dir) / "openhands_events.jsonl"
    lines = [json.dumps(event, sort_keys=True) for event in events]
    return _write_text(path, "\n".join(lines) + "\n")


def write_worker_scorecard(run_dir: Path, scorecard: WorkerScorecard) -> Path:
    return _write_json(_ensure_run_dir(run_dir) / "worker_scorecard.json", scorecard)


def collect_worker_artifact_paths(
    *,
    prompt: Path,
    stdout: Path,
    stderr: Path,
    summary: Path,
    result: Path,
    events: Path | None = None,
    scorecard: Path | None = None,
) -> WorkerArtifactPaths:
    return WorkerArtifactPaths(
        prompt=str(prompt),
        stdout=str(stdout),
        stderr=str(stderr),
        summary=str(summary),
        result=str(result),
        events=str(events) if events else None,
        scorecard=str(scorecard) if scorecard else None,
    )
