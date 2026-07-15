import json
from pathlib import Path

from app.core.workers.openhands_artifacts import (
    read_worker_summary,
    write_worker_events,
    write_worker_logs,
    write_worker_prompt,
    write_worker_result,
    write_worker_scorecard,
    write_worker_summary,
)
from app.schemas.edit import ExternalEditResult
from app.schemas.worker_loop import WorkerLoopSummary, WorkerScorecard


def test_openhands_artifact_writer_persists_worker_files(tmp_path: Path) -> None:
    prompt_path = write_worker_prompt(tmp_path, "# Worker Packet\nDo work")
    stdout_path, stderr_path = write_worker_logs(tmp_path, "out", "err")
    summary_path = write_worker_summary(
        tmp_path,
        WorkerLoopSummary(
            status="completed",
            model="anthropic/test",
            tools_requested=["terminal", "file_editor"],
        ),
    )
    result_path = write_worker_result(
        tmp_path,
        ExternalEditResult(
            status="completed",
            command="python -m app.core.workers.openhands_runner",
            exit_code=0,
            stdout="out",
            stderr="",
            duration_seconds=1.25,
        ),
    )
    scorecard_path = write_worker_scorecard(
        tmp_path,
        WorkerScorecard(
            task_id="run-1",
            status="completed",
            duration_seconds=1.25,
        ),
    )
    events_path = write_worker_events(tmp_path, [{"event": "start"}, {"event": "complete"}])

    assert prompt_path.name == "worker_prompt.md"
    assert prompt_path.read_text(encoding="utf-8").startswith("# Worker Packet")
    assert stdout_path.read_text(encoding="utf-8") == "out"
    assert stderr_path.read_text(encoding="utf-8") == "err"
    assert json.loads(summary_path.read_text(encoding="utf-8"))["loop_owner"] == "openhands_sdk"
    assert json.loads(result_path.read_text(encoding="utf-8"))["exit_code"] == 0
    assert json.loads(scorecard_path.read_text(encoding="utf-8"))["worker_type"] == "openhands"
    assert events_path is not None
    assert events_path.read_text(encoding="utf-8").count("\n") == 2


def test_read_worker_summary_is_safe_for_missing_malformed_and_valid_files(tmp_path: Path) -> None:
    assert read_worker_summary(tmp_path) is None

    summary_path = tmp_path / "worker_loop_summary.json"
    summary_path.write_text("{malformed}", encoding="utf-8")
    assert read_worker_summary(tmp_path) is None

    expected = WorkerLoopSummary(status="completed", tools_requested=["terminal"])
    write_worker_summary(tmp_path, expected)
    assert read_worker_summary(tmp_path) == expected
