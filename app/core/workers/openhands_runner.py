"""Subprocess entry point that runs one OpenHands SDK agent loop over a repo.

Kept as a separate process so the heavy `openhands` import is lazy and the run is
timeout-bounded by the parent worker (the same subprocess pattern the CLI workers use).
Implements the slide-16 six steps against the real OpenHands SDK 1.28 API:
LLM -> Agent(tools) -> Conversation(workspace=repo) -> send_message -> run; the harness
reads the resulting git diff itself (step 6).

Reads the task prompt from stdin (avoids CLI arg-length limits). argv: <repo_path> [model].
Exit codes: 0 ok · 2 usage · 3 auth missing · 4 sdk not installed · 1 run error.
"""

from __future__ import annotations

import os
import sys

DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: openhands_runner <repo_path> [model]  (task on stdin)", file=sys.stderr)
        return 2
    repo_path = sys.argv[1]
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
        from openhands.tools.file_editor import FileEditorTool
        from openhands.tools.terminal import TerminalTool
    except ImportError as exc:
        print(f"openhands sdk not installed: {exc}", file=sys.stderr)
        return 4

    try:
        llm = LLM(model=model, api_key=api_key)
        agent = Agent(
            llm=llm,
            tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)],
        )
        conversation = Conversation(agent=agent, workspace=str(repo_path))
        conversation.send_message(task)
        conversation.run()
    except Exception as exc:  # surface as a worker failure, not a crash
        print(f"openhands run error: {exc}", file=sys.stderr)
        return 1

    print("openhands run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
