from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.graph import run_harness
from app.core.handoff import handoff_document_json, render_handoff_markdown, worker_handoff_from_run
from app.core.llm import LLMClient, build_runtime_llm_client
from app.core.storage import RunStorage


class CreateRunRequest(BaseModel):
    repo_path: Path
    task: str
    test_commands: list[str] | None = None
    worker_command: str | None = None
    worker_timeout_seconds: int = 300
    allow_dirty: bool = False


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
    def list_runs(limit: int = 20) -> list[dict[str, str]]:
        return [
            {
                "run_id": record.run_id,
                "task": record.task,
                "status": record.status,
                "risk_level": record.risk_report.risk_level,
            }
            for record in RunStorage(selected_storage).list(limit=limit)
        ]

    @api.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            record = RunStorage(selected_storage).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return record.model_dump(mode="json")

    @api.get("/runs/{run_id}/report")
    def get_report(run_id: str) -> dict[str, str]:
        try:
            record = RunStorage(selected_storage).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run_id": record.run_id, "report": record.final_report.markdown}

    @api.get("/runs/{run_id}/logs")
    def get_logs(run_id: str) -> dict[str, str | list[str]]:
        try:
            record = RunStorage(selected_storage).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run_id": record.run_id, "logs": record.execution_logs}

    @api.get("/runs/{run_id}/handoff", response_model=None)
    def get_handoff(
        run_id: str,
        response_format: Literal["markdown", "json"] = Query(
            default="markdown",
            alias="format",
        ),
    ) -> PlainTextResponse | dict:
        try:
            record = RunStorage(selected_storage).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        packet = worker_handoff_from_run(record)
        if response_format == "json":
            return handoff_document_json(packet)
        return PlainTextResponse(
            render_handoff_markdown(packet),
            media_type="text/markdown; charset=utf-8",
        )

    return api


api = create_api()
