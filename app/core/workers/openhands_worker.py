"""OpenHands SDK worker — runs a real OpenHands agent loop as a subprocess.

Follows the slide-16 six-step SDK pattern (workspace -> agent -> conversation ->
run -> extract diff) against the real OpenHands SDK 1.28 API. The agent runs in a
child process (`app.core.workers.openhands_runner`) so the heavy import is lazy and
the run is timeout-bounded, exactly like the CLI workers. The worker edits the repo
in place; the harness reads the diff (step 6) via its existing collect_diff node.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.core.git_utils import collect_status_lines, is_git_repo
from app.core.packs.loader import build_pack_provenance, load_pack, resolve_tool_names
from app.core.workers.auth_errors import detect_auth_failure
from app.core.workers.openhands_artifacts import (
    write_worker_logs,
    write_worker_prompt,
    write_worker_result,
    write_worker_scorecard,
    write_worker_summary,
)
from app.core.workers.openhands_config import OPENHANDS_TOOL_NAMES
from app.core.workers.openhands_runner import SUMMARY_PREFIX
from app.prompts.workers import build_worker_prompt
from app.schemas.edit import ExternalEditResult
from app.schemas.pack import CapabilityPackProvenance
from app.schemas.worker_loop import WorkerLoopSummary, WorkerScorecard

COMMAND_STR = "python -m app.core.workers.openhands_runner <repo> (task on stdin)"
HARNESS_ROOT = Path(__file__).resolve().parents[3]


class OpenHandsWorker:
    """Run an OpenHands SDK agent over a repository inside the harness."""

    def run(
        self,
        repo_path: Path,
        task: str,
        timeout_seconds: int = 300,
        allow_dirty: bool = False,
        run_dir: Path | None = None,
        run_id: str | None = None,
        plan: Any = None,
        repo_profile: Any = None,
        tests_to_run: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        permission_tier: str = "standard",
        workspace: str = "local",
        pack_path: str | None = None,
    ) -> ExternalEditResult:
        command = f"{sys.executable} -m app.core.workers.openhands_runner {repo_path}"
        if not is_git_repo(repo_path):
            return ExternalEditResult(
                status="blocked",
                command=command,
                stderr="Target path must be a git repository for edit attribution.",
                termination_reason="not_git_repo",
                worker_type="openhands",
            )

        if collect_status_lines(repo_path) and not allow_dirty:
            return ExternalEditResult(
                status="blocked",
                command=command,
                stderr=(
                    "Target repository is dirty. Commit, stash, or pass allow_dirty=True "
                    "before running an OpenHands worker."
                ),
                termination_reason="dirty_repo",
                worker_type="openhands",
            )

        prompt = build_worker_prompt(
            repo_path=repo_path,
            task=task,
            plan=plan,
            repo_profile=repo_profile,
            forbidden_paths=forbidden_paths,
            tests_to_run=tests_to_run,
            permission_tier=permission_tier,
        )
        argv = [sys.executable, "-m", "app.core.workers.openhands_runner", str(repo_path)]
        prompt_path = write_worker_prompt(run_dir, prompt) if run_dir else None
        resolved_tool_names = list(OPENHANDS_TOOL_NAMES)
        pack_provenance = None
        if pack_path:
            capability_pack = load_pack(Path(pack_path))
            resolved_tool_names = resolve_tool_names(capability_pack, resolved_tool_names)
            pack_provenance = build_pack_provenance(capability_pack, resolved_tool_names)

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                cwd=HARNESS_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=_runner_env(run_dir, workspace, pack_path),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_text(exc.stdout or exc.output or "")
            stderr = _coerce_text(
                exc.stderr or f"OpenHands worker timed out after {timeout_seconds}s."
            )
            duration = round(time.perf_counter() - started, 3)
            result = ExternalEditResult(
                status="timeout",
                command=command,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                termination_reason="timeout",
                worker_type="openhands",
            )
            summary = WorkerLoopSummary(
                status="timeout",
                exit_code=None,
                duration_seconds=duration,
                tools_requested=resolved_tool_names,
                termination_reason="timeout",
                prompt_path=str(prompt_path) if prompt_path else None,
                capability_pack=pack_provenance,
            )
            _persist_worker_artifacts(
                run_dir=run_dir,
                run_id=run_id,
                prompt_path=prompt_path,
                prompt=prompt,
                result=result,
                summary=summary,
            )
            return result

        duration = round(time.perf_counter() - started, 3)
        code = completed.returncode
        summary = _summary_from_stdout(
            completed.stdout,
            fallback_tools_requested=resolved_tool_names,
            fallback_capability_pack=pack_provenance,
        ) or WorkerLoopSummary(
            status=_status_from_exit_code(code, completed.stdout, completed.stderr),
            exit_code=code,
            duration_seconds=duration,
            tools_requested=resolved_tool_names,
            termination_reason=_termination_from_exit_code(
                code,
                completed.stdout,
                completed.stderr,
            ),
            capability_pack=pack_provenance,
        )
        summary.exit_code = code
        summary.duration_seconds = duration
        summary.prompt_path = str(prompt_path) if prompt_path else None

        status = _status_from_exit_code(code, completed.stdout, completed.stderr)
        termination_reason = _termination_from_exit_code(code, completed.stdout, completed.stderr)
        stderr = _stderr_with_setup_hint(status, completed.stdout, completed.stderr)
        result = ExternalEditResult(
            status=status,
            command=command,
            exit_code=code,
            stdout=completed.stdout,
            stderr=stderr,
            duration_seconds=duration,
            termination_reason=termination_reason,
            worker_type="openhands",
        )
        summary.status = status
        summary.termination_reason = termination_reason
        _persist_worker_artifacts(
            run_dir=run_dir,
            run_id=run_id,
            prompt_path=prompt_path,
            prompt=prompt,
            result=result,
            summary=summary,
        )
        return result


def _coerce_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _runner_env(
    run_dir: Path | None = None,
    workspace: str = "local",
    pack_path: str | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(HARNESS_ROOT) if not existing else f"{HARNESS_ROOT}{os.pathsep}{existing}"
    )
    # Select the OpenHands workspace mode for the runner (local in-process loop, or its
    # own Docker agent-server container).
    env["OPENHANDS_WORKSPACE"] = "docker" if workspace == "docker" else "local"
    # The outer loop's selected capability pack, loaded by the runner before it
    # assembles the agent (skills → system suffix, tools → allowlist, hooks → callbacks).
    if pack_path:
        env["OPENHANDS_PACK_PATH"] = pack_path
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "openhands_events.jsonl"
        persistence_dir = run_dir / "openhands_state"
        events_path.touch(exist_ok=True)
        persistence_dir.mkdir(parents=True, exist_ok=True)
        env["OPENHANDS_EVENTS_PATH"] = str(events_path)
        env["OPENHANDS_PERSISTENCE_DIR"] = str(persistence_dir)
    return env


def _summary_from_stdout(
    stdout: str,
    *,
    fallback_tools_requested: list[str] | None = None,
    fallback_capability_pack: CapabilityPackProvenance | None = None,
) -> WorkerLoopSummary | None:
    for line in stdout.splitlines():
        if not line.startswith(SUMMARY_PREFIX):
            continue
        try:
            return WorkerLoopSummary.model_validate_json(line.split("=", maxsplit=1)[1])
        except (json.JSONDecodeError, ValueError):
            return WorkerLoopSummary(
                status="failed",
                tools_requested=list(fallback_tools_requested or OPENHANDS_TOOL_NAMES),
                termination_reason="malformed_worker_summary",
                notes=["OpenHands runner emitted malformed summary JSON."],
                capability_pack=fallback_capability_pack,
            )
    return None


def _status_from_exit_code(code: int, stdout: str, stderr: str) -> str:
    if code == 0:
        return "completed"
    if code == 3 or detect_auth_failure(stdout, stderr):
        return "auth_missing"
    if code == 4:
        return "setup_missing"
    if code == 6:
        # Bad config (e.g. OPENHANDS_MAX_ITERATIONS=bad) is NOT a missing SDK, so it must
        # not get the "reinstall the SDK" hint. The runner already prints the real cause
        # to stderr ("configuration_error: ...").
        return "configuration_error"
    return "failed"


def _termination_from_exit_code(code: int, stdout: str, stderr: str) -> str:
    if code == 0:
        return "completed"
    if code == 2:
        return "usage_error"
    if code == 3 or detect_auth_failure(stdout, stderr):
        return "auth_missing"
    if code == 4:
        return "sdk_missing"
    if code == 6:
        return "configuration_error"
    return "run_error"


def _stderr_with_setup_hint(status: str, stdout: str, stderr: str) -> str:
    if status == "setup_missing":
        hint = "OpenHands SDK not importable (it is a core dependency). Reinstall with: uv sync."
        return f"{hint}\n{stderr}".strip()
    if status == "auth_missing":
        hint = detect_auth_failure(stdout, stderr) or (
            "OpenHands authentication missing. Set LLM_API_KEY, ANTHROPIC_API_KEY, "
            "or OPENAI_API_KEY and retry."
        )
        return f"{hint}\n{stderr}".strip()
    return stderr


def _persist_worker_artifacts(
    *,
    run_dir: Path | None,
    run_id: str | None,
    prompt_path: Path | None,
    prompt: str,
    result: ExternalEditResult,
    summary: WorkerLoopSummary,
) -> None:
    if run_dir is None:
        return

    if prompt_path is None:
        prompt_path = write_worker_prompt(run_dir, prompt)
    stdout_path, stderr_path = write_worker_logs(run_dir, result.stdout, result.stderr)
    events_path = _existing_event_log_path(run_dir, summary)
    summary.prompt_path = str(prompt_path)
    summary.stdout_path = str(stdout_path)
    summary.stderr_path = str(stderr_path)
    if events_path:
        summary.event_log_path = str(events_path)
    summary_path = write_worker_summary(run_dir, summary)
    scorecard_path = write_worker_scorecard(
        run_dir,
        WorkerScorecard(
            task_id=run_id,
            status=result.status,
            duration_seconds=result.duration_seconds,
            tests_attempted_by_worker=_worker_attempted_tests(result.stdout, result.stderr),
            notes=[
                "AgentOps owns final diff collection, permission enforcement, tests, "
                "risk, and evidence."
            ],
        ),
    )
    result.artifact_paths = {
        "prompt": str(prompt_path),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "summary": str(summary_path),
        "events": str(events_path) if events_path else None,
        "scorecard": str(scorecard_path),
    }
    # write_worker_result owns the filename; use its return value rather than
    # re-deriving the path so the two can never drift apart.
    result_path = write_worker_result(run_dir, result)
    result.artifact_paths["result"] = str(result_path)


def _existing_event_log_path(run_dir: Path, summary: WorkerLoopSummary) -> Path | None:
    candidates = []
    if summary.event_log_path:
        candidates.append(Path(summary.event_log_path))
    candidates.append(run_dir / "openhands_events.jsonl")
    for path in candidates:
        # The recorder pre-touches the log even when zero callbacks fire; treat an empty
        # file as "no events captured" so artifact_paths["events"] is set iff events exist.
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _worker_attempted_tests(stdout: str, stderr: str) -> bool | None:
    blob = f"{stdout}\n{stderr}".lower()
    # "pytest" already covers "uv run pytest"; a bare "uv run" would false-positive on
    # "uv run black ." / "uv run pip install", so only the explicit test script counts.
    if any(marker in blob for marker in ("pytest", "unittest", "npm test", "uv run test")):
        return True
    return None
