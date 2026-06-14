"""Mount the cockpit (API routes + static UI) onto the FastAPI app.

Read endpoints live under ``/cockpit/api`` and the vanilla static UI is served
at ``/cockpit``. The API routes are registered *before* the static mount so an
exact route like ``/cockpit/api/runs`` is matched ahead of the ``/cockpit`` mount.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app.cockpit.artifacts import CockpitReader, _normalize_inner_event
from app.core.run_artifacts import artifact_dir_for_run, export_artifact_bundle

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

# Seconds between replayed trajectory events — fast enough to feel live, slow
# enough to read. Live (in-flight) tails emit as soon as a line is appended.
_REPLAY_GAP = 0.12
_TAIL_IDLE_LIMIT = 50  # ~5s of no new lines on a live file ends the stream


def build_router(reader: CockpitReader) -> APIRouter:
    router = APIRouter(prefix="/cockpit/api", tags=["cockpit"])

    @router.get("/runs")
    def list_runs(limit: int = 50) -> dict:
        return reader.list_summaries(limit=limit)

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            return reader.detail(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs/{run_id}/bundle.zip", response_model=None)
    def get_bundle(run_id: str) -> FileResponse:
        run_dir = artifact_dir_for_run(reader.storage_path, run_id)
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"No artifacts for run: {run_id}")
        out = Path(tempfile.gettempdir()) / f"agentops-run-{run_id}.zip"
        export_artifact_bundle(run_dir, out)
        # Delete the temp zip once the response is sent so they don't accumulate.
        return FileResponse(
            out,
            media_type="application/zip",
            filename=f"run-{run_id[:8]}.zip",
            background=BackgroundTask(out.unlink, missing_ok=True),
        )

    @router.get("/runs/{run_id}/artifacts/{name}", response_model=None)
    def get_artifact(run_id: str, name: str) -> PlainTextResponse:
        try:
            return PlainTextResponse(reader.artifact_text(run_id, name))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs/{run_id}/stream")
    def stream_run(run_id: str) -> StreamingResponse:
        return _event_stream(_sse_governance(reader, run_id))

    @router.get("/runs/{run_id}/worker/stream")
    def stream_worker(run_id: str) -> StreamingResponse:
        return _event_stream(_sse_worker(reader, run_id))

    return router


def _event_stream(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def mount_cockpit(api: FastAPI, storage_path: Path) -> None:
    reader = CockpitReader(storage_path)
    api.include_router(build_router(reader))
    if WEB_DIR.is_dir():
        api.mount("/cockpit", StaticFiles(directory=WEB_DIR, html=True), name="cockpit")


def _sse_message(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _sse_governance(reader: CockpitReader, run_id: str) -> AsyncIterator[str]:
    """Outer loop: replay the governance node trajectory (trace.jsonl)."""
    try:
        events = reader.trajectory(run_id)
    except KeyError:
        yield _sse_message("error", {"detail": f"Run not found: {run_id}"})
        return
    yield _sse_message("open", {"run_id": run_id})
    for event in events:
        yield _sse_message("event", event)
        await asyncio.sleep(_REPLAY_GAP)
    yield _sse_message("done", {"run_id": run_id})


async def _sse_worker(reader: CockpitReader, run_id: str) -> AsyncIterator[str]:
    """Inner loop: follow the openhands event log — backlog first, then live appends."""
    yield _sse_message("open", {"run_id": run_id})
    live_path = reader.live_event_path(run_id)
    if live_path.exists():
        async for message in _tail_live(live_path):
            yield message
    yield _sse_message("done", {"run_id": run_id})


async def _tail_live(path: Path) -> AsyncIterator[str]:
    """Emit the existing events, then follow the file for ones appended live.

    Handles both a finished run (emit the backlog, then idle out) and an in-flight
    run (emit the backlog, then keep streaming as the worker appends). Reads
    off-thread so the event loop is never blocked, and only consumes complete,
    newline-terminated lines so a partially-written trailing line is left for the
    next pass instead of raising a JSON error.
    """
    offset = 0
    idle = 0
    index = 0
    while idle < _TAIL_IDLE_LIMIT:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        last_newline = text.rfind("\n", offset)
        if last_newline < offset:
            idle += 1
            await asyncio.sleep(0.1)
            continue
        complete = text[offset : last_newline + 1]
        offset = last_newline + 1
        idle = 0
        for line in complete.splitlines():
            if not line.strip():
                continue
            try:
                event = _normalize_inner_event(index, json.loads(line))
            except json.JSONDecodeError:
                continue
            yield _sse_message("event", event)
            index += 1
            await asyncio.sleep(_REPLAY_GAP)
