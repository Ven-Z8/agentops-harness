"""Subprocess entry point for the OpenHands inner-loop worker.

The parent AgentOps worker owns repo attribution, timeout, artifact persistence,
and post-worker governance. This subprocess owns only SDK setup and the
OpenHands conversation loop. Keeping the SDK import here makes OpenHands an
optional dependency for normal AgentOps runs and tests.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.core.packs.loader import (
    assemble_agent_inputs,
    build_pack_provenance,
    load_pack,
    resolve_tool_names,
)
from app.core.workers.openhands_config import (
    OPENHANDS_TOOL_NAMES,
    load_openhands_config,
    openhands_sdk_available,
)
from app.schemas.pack import CapabilityPack, CapabilityPackProvenance
from app.schemas.worker_loop import WorkerLoopSummary

EXIT_RUN_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_AUTH_MISSING = 3
EXIT_SDK_MISSING = 4
EXIT_CONFIGURATION_ERROR = 6
SUMMARY_PREFIX = "OPENHANDS_WORKER_SUMMARY_JSON="

# Injected as the agent's system-prompt suffix — the AgentOps-harness constraints
# (the bridge between the outer governor and the inner OpenHands loop).
HARNESS_SYSTEM_SUFFIX = (
    "\n\nYou are running as a worker inside the AgentOps Harness. Constraints:\n"
    "- Make the smallest controlled change that satisfies the task; do not refactor "
    "unrelated code.\n"
    "- Do not edit secrets, auth, payment, or dependency files without being asked.\n"
    "- Add or update a focused test for new behavior, then run the tests to verify.\n"
    "- If blocked, summarize the blocker instead of a speculative large change."
)


class _OpenHandsEventRecorder:
    def __init__(self, event_log_path: str | None) -> None:
        self.event_log_path = event_log_path
        self.observable_event_count = 0
        self.write_error: str | None = None
        if event_log_path:
            path = Path(event_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

    def __call__(self, event: Any) -> None:
        self.observable_event_count += 1
        if not self.event_log_path:
            return
        payload = {
            "event_type": event.__class__.__name__,
            "event": _serialize_event(event),
        }
        try:
            with Path(self.event_log_path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            self.write_error = str(exc)


def _load_capability_pack() -> CapabilityPack | None:
    """Load the outer loop's selected pack, if any, from OPENHANDS_PACK_PATH."""
    pack_path = os.getenv("OPENHANDS_PACK_PATH")
    if not pack_path:
        return None
    return load_pack(Path(pack_path))


def _serialize_event(event: Any) -> dict[str, Any] | str:
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    if hasattr(event, "dict"):
        return event.dict()
    return repr(event)


def _emit_summary(summary: WorkerLoopSummary) -> None:
    print(SUMMARY_PREFIX + json.dumps(summary.model_dump(mode="json"), sort_keys=True))


def _summary(
    *,
    status: str,
    model: str | None,
    started: float,
    exit_code: int | None = None,
    event_log_path: str | None = None,
    observable_event_count: int = 0,
    termination_reason: str | None = None,
    setup_error: str | None = None,
    notes: list[str] | None = None,
    tools_requested: list[str] | None = None,
    capability_pack: CapabilityPackProvenance | None = None,
) -> WorkerLoopSummary:
    return WorkerLoopSummary(
        model=model,
        status=status,
        exit_code=exit_code,
        duration_seconds=round(time.perf_counter() - started, 3),
        tools_requested=list(tools_requested or OPENHANDS_TOOL_NAMES),
        event_log_path=event_log_path,
        observable_event_count=observable_event_count,
        termination_reason=termination_reason,
        setup_error=setup_error,
        notes=notes
        or ["Inner tool trajectory may be partially observable depending on SDK support."],
        capability_pack=capability_pack,
    )


def build_agent(llm: Any, pack: CapabilityPack | None) -> tuple[Any, list[str], list[Any]]:
    """Assemble the OpenHands agent — the 9-component wiring + any capability pack.

    Pure construction (no conversation run, no network), extracted so it is unit-testable
    against the REAL OpenHands SDK without an API call. Returns (agent, tool_names, hooks).
    Requires the OpenHands SDK to be importable (it is a core dependency).
    """
    from openhands.sdk import Agent, Tool
    from openhands.sdk.context import AgentContext
    from openhands.sdk.context.condenser import LLMSummarizingCondenser

    # Importing the tool modules registers them so Tool(name=...) resolves at runtime.
    from openhands.tools import glob as _glob  # noqa: F401 (registers retrieval)
    from openhands.tools import grep as _grep  # noqa: F401 (registers retrieval)
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.preset import register_builtins_agents
    from openhands.tools.task import TaskToolSet  # 04 sub-agent delegation tool
    from openhands.tools.task_tracker import TaskTrackerTool
    from openhands.tools.terminal import TerminalTool

    # 04 sub-agents — register the terminal-only archetypes (no web-researcher), honoring the
    # harness's no-browser/network constraint; sub-agents inherit only terminal/file tools.
    register_builtins_agents(enable_browser=False)
    # 02 context management.
    condenser = LLMSummarizingCondenser(llm=llm, max_size=80, keep_first=4)
    available_tools = {
        "terminal": Tool(name=TerminalTool.name),
        "file_editor": Tool(name=FileEditorTool.name),
        "task_tracker": Tool(name=TaskTrackerTool.name),
        "grep": Tool(name="grep"),
        "glob": Tool(name="glob"),
        "task_tool_set": Tool(name=TaskToolSet.name),
    }
    # 03/07 skills + system-prompt assembly (the AgentOps constraints bridge), folding in any
    # capability pack: pack skills extend the suffix, pack tools restrict the set, pack hooks
    # become callbacks.
    system_suffix, tool_names, pack_hooks = assemble_agent_inputs(
        pack,
        base_system_suffix=HARNESS_SYSTEM_SUFFIX,
        default_tools=list(available_tools),
    )
    agent_context = AgentContext(
        system_message_suffix=system_suffix,
        load_project_skills=True,
    )
    # 05 primitives + retrieval; 04 delegation (task_tool_set spawns sub-agents). NOTE: the
    # 09 security analyzer is NOT an Agent kwarg in SDK 1.28 (it is silently dropped) — it is
    # attached to the conversation state in main() via conversation.set_security_analyzer().
    agent = Agent(
        llm=llm,
        tools=[available_tools[name] for name in tool_names if name in available_tools],
        condenser=condenser,
        agent_context=agent_context,
    )
    return agent, tool_names, pack_hooks


def main() -> int:
    started = time.perf_counter()
    if len(sys.argv) < 2:
        print("usage: openhands_runner <repo_path> [model]  (task on stdin)", file=sys.stderr)
        return EXIT_USAGE_ERROR
    repo_path = sys.argv[1]
    task = sys.stdin.read().strip()
    if not task:
        print("usage: task prompt must be provided on stdin", file=sys.stderr)
        return EXIT_USAGE_ERROR

    config = load_openhands_config()
    model = sys.argv[2] if len(sys.argv) > 2 else config.model
    if config.config_error:
        print(f"configuration_error: {config.config_error}", file=sys.stderr)
        _emit_summary(
            _summary(
                status="failed",
                model=model,
                started=started,
                exit_code=EXIT_CONFIGURATION_ERROR,
                termination_reason="configuration_error",
                setup_error=config.config_error,
            )
        )
        return EXIT_CONFIGURATION_ERROR

    if not openhands_sdk_available():
        message = "OpenHands SDK not importable (it is a core dependency). Reinstall with: uv sync"
        print(f"setup_missing: {message}", file=sys.stderr)
        _emit_summary(
            _summary(
                status="setup_missing",
                model=model,
                started=started,
                exit_code=EXIT_SDK_MISSING,
                termination_reason="sdk_missing",
                setup_error=message,
            )
        )
        return EXIT_SDK_MISSING

    if config.missing_auth:
        message = (
            "set LLM_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, or configure "
            "AGENTOPS_OPENROUTER_API_KEY"
        )
        print(f"authentication_error: {message}", file=sys.stderr)
        _emit_summary(
            _summary(
                status="auth_missing",
                model=model,
                started=started,
                exit_code=EXIT_AUTH_MISSING,
                termination_reason="auth_missing",
                setup_error=message,
            )
        )
        return EXIT_AUTH_MISSING

    api_key = os.getenv(config.api_key_env or "")
    event_recorder = _OpenHandsEventRecorder(os.getenv("OPENHANDS_EVENTS_PATH"))
    persistence_dir = os.getenv("OPENHANDS_PERSISTENCE_DIR") or None
    workspace_mode = os.getenv("OPENHANDS_WORKSPACE", "local").lower()

    try:
        pack = _load_capability_pack()
        tool_names = (
            resolve_tool_names(pack, list(OPENHANDS_TOOL_NAMES))
            if pack is not None
            else list(OPENHANDS_TOOL_NAMES)
        )
        pack_provenance = build_pack_provenance(pack, tool_names) if pack is not None else None
    except Exception as exc:  # a misconfigured pack is a config error, not a crash
        message = f"capability pack failed to load: {exc}"
        print(f"configuration_error: {message}", file=sys.stderr)
        _emit_summary(
            _summary(
                status="failed",
                model=model,
                started=started,
                exit_code=EXIT_CONFIGURATION_ERROR,
                termination_reason="pack_error",
                setup_error=message,
            )
        )
        return EXIT_CONFIGURATION_ERROR

    try:
        # main() drives the conversation; build_agent (below) imports and validates the full
        # tool/context/security surface when it constructs the agent.
        from openhands.sdk import LLM, Conversation
    except ImportError as exc:
        message = f"OpenHands SDK not installed or incomplete: {exc}"
        print(f"setup_missing: {message}", file=sys.stderr)
        _emit_summary(
            _summary(
                status="setup_missing",
                model=model,
                started=started,
                exit_code=EXIT_SDK_MISSING,
                termination_reason="sdk_missing",
                setup_error=message,
            )
        )
        return EXIT_SDK_MISSING

    workspace = None
    try:
        llm_kwargs = {"model": model, "api_key": api_key}
        if config.base_url is not None:
            llm_kwargs["base_url"] = config.base_url
        if config.openrouter_site_url is not None:
            llm_kwargs["openrouter_site_url"] = config.openrouter_site_url
        if config.openrouter_app_name is not None:
            llm_kwargs["openrouter_app_name"] = config.openrouter_app_name
        llm = LLM(**llm_kwargs)
        # 02-09 component wiring + capability-pack injection. Extracted to build_agent so it is
        # unit-testable against the real SDK. Kept inside the try so a construction/registration
        # failure still emits a summary + EXIT_RUN_ERROR instead of crashing main().
        agent, built_tool_names, pack_hooks = build_agent(llm, pack)
        assert built_tool_names == tool_names, (
            "OpenHands agent tool resolution drifted from the precomputed worker summary: "
            f"{built_tool_names!r} != {tool_names!r}"
        )
        notes = [
            "OpenHands SDK controls the inner prompt-model-tool-observe loop.",
            "Observable SDK events are captured through Conversation callbacks.",
        ]
        if pack is not None:
            notes.append(f"Capability pack loaded: {pack.manifest.name} ({pack.manifest.domain}).")
        conversation_kwargs: dict[str, Any] = {
            "agent": agent,
            # 08 hooks: pack-defined callbacks fire alongside the event recorder.
            "callbacks": [event_recorder, *pack_hooks],
            "stuck_detection": True,  # 08 hooks: break no-progress loops
        }
        if workspace_mode == "docker":
            # The agent's repo lives at /workspace/project; bind-mount the host repo THERE
            # so edits reflect back to the host (bidirectional, no extraction needed).
            from openhands.workspace import DockerWorkspace

            workspace = DockerWorkspace(
                working_dir="/workspace",
                volumes=[f"{os.path.abspath(repo_path)}:/workspace/project"],
                forward_env=[
                    "OPENHANDS_MODEL",
                ],
            )
            conversation_kwargs["workspace"] = workspace
            notes.append("OpenHands agent loop runs inside an isolated Docker container.")
            # RemoteConversation (docker) persists in-container; persistence_dir is forbidden.
        else:
            conversation_kwargs["workspace"] = str(repo_path)
            if persistence_dir:
                conversation_kwargs["persistence_dir"] = persistence_dir
                notes.append("OpenHands conversation persistence directory was configured.")
        if config.max_iterations is not None:
            conversation_kwargs["max_iteration_per_run"] = config.max_iterations
        conversation = Conversation(**conversation_kwargs)
        # 09 security/safety — attach the LLM security analyzer to the conversation state (the
        # SDK-1.28 mechanism; it is NOT an Agent kwarg) so each pending action is risk-assessed.
        from openhands.sdk.security.llm_analyzer import LLMSecurityAnalyzer

        conversation.set_security_analyzer(LLMSecurityAnalyzer())
        conversation.send_message(task)
        conversation.run()
    except Exception as exc:  # surface as a worker failure, not a crash
        print(f"openhands run error: {exc}", file=sys.stderr)
        notes = ["OpenHands SDK run failed before completion."]
        if event_recorder.write_error:
            notes.append(f"OpenHands event log write failed: {event_recorder.write_error}")
        _emit_summary(
            _summary(
                status="failed",
                model=model,
                started=started,
                exit_code=EXIT_RUN_ERROR,
                event_log_path=event_recorder.event_log_path,
                observable_event_count=event_recorder.observable_event_count,
                termination_reason="run_error",
                notes=notes,
                tools_requested=tool_names,
                capability_pack=pack_provenance,
            )
        )
        return EXIT_RUN_ERROR
    finally:
        # Clean up the docker workspace container if one was started.
        if workspace is not None:
            with contextlib.suppress(Exception):
                workspace.close()

    if event_recorder.write_error:
        notes.append(f"OpenHands event log write failed: {event_recorder.write_error}")
    _emit_summary(
        _summary(
            status="completed",
            model=model,
            started=started,
            exit_code=0,
            event_log_path=event_recorder.event_log_path,
            observable_event_count=event_recorder.observable_event_count,
            termination_reason="completed",
            notes=notes,
            tools_requested=tool_names,
            capability_pack=pack_provenance,
        )
    )
    print("openhands run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
