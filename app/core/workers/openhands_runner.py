"""Subprocess entry point that runs one full-capability OpenHands SDK agent loop.

Kept as a separate process so the heavy `openhands` import is lazy and the run is
timeout-bounded by the parent worker (the same subprocess pattern the CLI workers use).

Wires the worker-harness anatomy (harness-project slides 6-17) onto the real OpenHands
SDK 1.28 — we ADOPT these, we do not build them:
  01 while loop ............ Conversation.run()
  02 context management .... LLMSummarizingCondenser (condenser)
  03 tools & skills ........ Terminal/FileEditor/TaskTracker tools + AgentContext.skills
  05 built-in primitives ... Terminal + FileEditor tools
  06 session persistence ... Conversation(persistence_dir, conversation_id)
  07 system-prompt assembly  AgentContext.system_message_suffix  <- the AgentOps bridge
  09 permissions & safety .. OpenHands security analyzer + NeverConfirm (autonomous)

Workspace mode (env OPENHANDS_WORKSPACE):
  - "local" (default): the agent loop runs in-process, editing the repo on the host.
  - "docker": the agent loop runs INSIDE an OpenHands agent-server container, with the
    repo bind-mounted (mount_dir) so edits land on the host repo. Realizes slide 16.

Task prompt on stdin (avoids arg-length limits). argv: <repo_path> [model].
Exit codes: 0 ok · 2 usage · 3 auth missing · 4 sdk not installed · 1 run error.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid

DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"

HARNESS_SYSTEM_SUFFIX = (
    "\n\nYou are running as a worker inside the AgentOps Harness. Constraints:\n"
    "- Make the smallest controlled change that satisfies the task; do not refactor "
    "unrelated code.\n"
    "- Do not edit secrets, auth, payment, or dependency files without being asked.\n"
    "- Add or update a focused test for new behavior, then run the tests to verify.\n"
    "- If blocked, summarize the blocker instead of a speculative large change."
)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: openhands_runner <repo_path> [model]  (task on stdin)", file=sys.stderr)
        return 2
    repo_path = os.path.abspath(sys.argv[1])
    model = sys.argv[2] if len(sys.argv) > 2 else os.getenv("OPENHANDS_MODEL", DEFAULT_MODEL)
    task = sys.stdin.read().strip()
    if not task:
        print("usage: task prompt must be provided on stdin", file=sys.stderr)
        return 2

    api_key = os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("authentication_error: set ANTHROPIC_API_KEY or LLM_API_KEY", file=sys.stderr)
        return 3

    try:
        from openhands.sdk import LLM, Agent, Conversation, Tool
        from openhands.sdk.context import AgentContext
        from openhands.sdk.context.condenser import LLMSummarizingCondenser
        from openhands.tools.file_editor import FileEditorTool
        from openhands.tools.task_tracker import TaskTrackerTool
        from openhands.tools.terminal import TerminalTool
    except ImportError as exc:
        print(f"openhands sdk not installed: {exc}", file=sys.stderr)
        return 4

    workspace_mode = os.getenv("OPENHANDS_WORKSPACE", "local").lower()

    workspace = None
    try:
        llm = LLM(model=model, api_key=api_key)

        # 02 context management — summarize older history, keep recent + first turns verbatim.
        condenser = LLMSummarizingCondenser(llm=llm, max_size=80, keep_first=4)

        # 03/07 skills + system-prompt assembly — the AgentOps constraints are injected
        # here; load any skills/microagents the project ships.
        agent_context = AgentContext(
            system_message_suffix=HARNESS_SYSTEM_SUFFIX,
            load_project_skills=True,
        )

        # 03/05 tools — terminal (bash/grep), file editor (read/write/edit), task tracker.
        agent = Agent(
            llm=llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
                Tool(name=TaskTrackerTool.name),
            ],
            condenser=condenser,
            agent_context=agent_context,
        )

        # 01 while loop + workspace selection.
        if workspace_mode == "docker":
            from openhands.workspace import DockerWorkspace

            # The agent's repo lives at /workspace/project (Conversation default). Bind-mount
            # the host repo THERE (not /workspace) so the agent edits the real files and the
            # changes reflect straight back to the host — bidirectional, no extraction needed.
            workspace = DockerWorkspace(
                working_dir="/workspace",
                volumes=[f"{repo_path}:/workspace/project"],
                forward_env=["ANTHROPIC_API_KEY", "LLM_API_KEY", "OPENHANDS_MODEL"],
            )
            ws_arg = workspace
        else:
            ws_arg = repo_path

        # 06 session persistence — replayable event log per run. A docker workspace uses a
        # RemoteConversation that persists inside the container, so persistence_dir must NOT
        # be set there; it is only valid for the in-process LocalConversation.
        conv_kwargs: dict = {
            "agent": agent,
            "workspace": ws_arg,
            "conversation_id": uuid.uuid4(),
        }
        if workspace_mode == "docker":
            # The host repo is bind-mounted at /workspace/project, so the agent's edits
            # reflect straight back to the host — no extraction step required.
            conversation = Conversation(**conv_kwargs)
            conversation.send_message(task)
            conversation.run()
        else:
            with tempfile.TemporaryDirectory(prefix="agentops-oh-") as persist:
                conversation = Conversation(persistence_dir=persist, **conv_kwargs)
                conversation.send_message(task)
                conversation.run()
    except Exception as exc:  # surface as a worker failure, not a crash
        print(f"openhands run error: {exc}", file=sys.stderr)
        return 1
    finally:
        # Clean up the docker workspace container if one was started.
        if workspace is not None:
            try:
                workspace.close()
            except Exception:
                pass

    print(f"openhands run complete (workspace={workspace_mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
