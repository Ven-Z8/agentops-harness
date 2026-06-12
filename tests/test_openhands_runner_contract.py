import json
import subprocess
import sys
from types import ModuleType


def _run_runner(repo: str = ".", task: str = "Do work", env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, "-m", "app.core.workers.openhands_runner", repo],
        input=task,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )


def _summary_from_stdout(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("OPENHANDS_WORKER_SUMMARY_JSON="):
            return json.loads(line.split("=", maxsplit=1)[1])
    raise AssertionError(f"summary line missing from stdout: {stdout}")


def _install_fake_openhands(monkeypatch, calls: dict, *, register_raises: bool = False) -> None:
    """Install a fake OpenHands SDK module tree into sys.modules and mark it available.

    The fakes record their constructor kwargs into ``calls`` so tests can assert how the
    runner wires the agent loop. With ``register_raises=True``, ``register_builtins_agents``
    raises — exercising the runner's contract that every failure still emits a
    ``OPENHANDS_WORKER_SUMMARY_JSON`` line and a clean exit code, never an uncaught crash.
    """

    class FakeEvent:
        def model_dump(self, *, mode: str):
            return {"id": "event-1", "source": "agent", "mode": mode}

    class FakeLLM:
        def __init__(self, **kwargs):
            calls["llm"] = kwargs

    class FakeTool:
        def __init__(self, **kwargs):
            calls.setdefault("tools", []).append(kwargs)

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent"] = kwargs

    class FakeConversation:
        def __init__(self, **kwargs):
            calls["conversation"] = kwargs

        def send_message(self, task: str) -> None:
            calls["task"] = task

        def run(self) -> None:
            calls["run_kwargs"] = {}
            for callback in calls["conversation"]["callbacks"]:
                callback(FakeEvent())

    class FakeAgentContext:
        def __init__(self, **kwargs):
            calls["agent_context"] = kwargs

    class FakeCondenser:
        def __init__(self, **kwargs):
            calls["condenser"] = kwargs

    class FakeSecurityAnalyzer:
        def __init__(self, **kwargs):
            calls["security_analyzer"] = kwargs

    sdk = ModuleType("openhands.sdk")
    sdk.LLM = FakeLLM
    sdk.Agent = FakeAgent
    sdk.Conversation = FakeConversation
    sdk.Tool = FakeTool

    sdk_context = ModuleType("openhands.sdk.context")
    sdk_context.AgentContext = FakeAgentContext
    sdk_condenser = ModuleType("openhands.sdk.context.condenser")
    sdk_condenser.LLMSummarizingCondenser = FakeCondenser
    sdk_security = ModuleType("openhands.sdk.security")
    sdk_security_analyzer = ModuleType("openhands.sdk.security.llm_analyzer")
    sdk_security_analyzer.LLMSecurityAnalyzer = FakeSecurityAnalyzer

    tools_pkg = ModuleType("openhands.tools")
    terminal = ModuleType("openhands.tools.terminal")
    terminal.TerminalTool = type("TerminalTool", (), {"name": "terminal"})
    file_editor = ModuleType("openhands.tools.file_editor")
    file_editor.FileEditorTool = type("FileEditorTool", (), {"name": "file_editor"})
    task_tracker = ModuleType("openhands.tools.task_tracker")
    task_tracker.TaskTrackerTool = type("TaskTrackerTool", (), {"name": "task_tracker"})
    task = ModuleType("openhands.tools.task")
    task.TaskToolSet = type("TaskToolSet", (), {"name": "task_tool_set"})
    glob_mod = ModuleType("openhands.tools.glob")
    grep_mod = ModuleType("openhands.tools.grep")
    preset = ModuleType("openhands.tools.preset")

    def _register_builtins_agents(*, enable_browser=True):
        if register_raises:
            raise RuntimeError("broken preset: archetype config missing")
        calls["builtins_registered"] = True
        calls["builtins_enable_browser"] = enable_browser
        return []

    preset.register_builtins_agents = _register_builtins_agents
    # `from openhands.tools import glob/grep` resolves the submodule attribute on the parent.
    tools_pkg.glob = glob_mod
    tools_pkg.grep = grep_mod

    fake_modules = {
        "openhands": ModuleType("openhands"),
        "openhands.sdk": sdk,
        "openhands.sdk.context": sdk_context,
        "openhands.sdk.context.condenser": sdk_condenser,
        "openhands.sdk.security": sdk_security,
        "openhands.sdk.security.llm_analyzer": sdk_security_analyzer,
        "openhands.tools": tools_pkg,
        "openhands.tools.terminal": terminal,
        "openhands.tools.file_editor": file_editor,
        "openhands.tools.task_tracker": task_tracker,
        "openhands.tools.task": task,
        "openhands.tools.glob": glob_mod,
        "openhands.tools.grep": grep_mod,
        "openhands.tools.preset": preset,
    }
    for name, mod in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    monkeypatch.setattr(
        "app.core.workers.openhands_runner.openhands_sdk_available",
        lambda: True,
    )
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENHANDS_MODEL", "test/model")


def test_runner_returns_usage_error_if_repo_path_missing() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.core.workers.openhands_runner"],
        input="Do work",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 2
    assert "usage:" in completed.stderr


def test_runner_returns_usage_error_if_stdin_task_missing() -> None:
    completed = _run_runner(task="")

    assert completed.returncode == 2
    assert "task prompt" in completed.stderr


def test_runner_returns_sdk_missing_before_auth_when_openhands_not_installed(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.workers.openhands_runner.openhands_sdk_available",
        lambda: False,
    )

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", "."])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "Do work"})())

    assert main() == 4


def test_runner_returns_auth_error_when_sdk_present_but_no_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.workers.openhands_runner.openhands_sdk_available",
        lambda: True,
    )
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", "."])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "Do work"})())

    assert main() == 3


def test_runner_returns_config_error_for_malformed_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENHANDS_MAX_ITERATIONS", "bad")

    completed = _run_runner(task="Do work", env={"OPENHANDS_MAX_ITERATIONS": "bad"})

    assert completed.returncode == 6
    assert "OPENHANDS_MAX_ITERATIONS" in completed.stderr


def test_runner_configures_sdk_loop_controls_and_event_capture(
    monkeypatch, tmp_path, capsys
) -> None:
    calls: dict[str, object] = {}
    _install_fake_openhands(monkeypatch, calls)
    monkeypatch.setenv("OPENHANDS_MAX_ITERATIONS", "7")
    events_path = tmp_path / "openhands_events.jsonl"
    persistence_dir = tmp_path / "openhands_state"
    monkeypatch.setenv("OPENHANDS_EVENTS_PATH", str(events_path))
    monkeypatch.setenv("OPENHANDS_PERSISTENCE_DIR", str(persistence_dir))

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", str(tmp_path)])
    monkeypatch.setattr(
        sys,
        "stdin",
        type("FakeStdin", (), {"read": lambda self: "Structured worker packet"})(),
    )

    assert main() == 0

    output = capsys.readouterr()
    summary = _summary_from_stdout(output.out)
    assert calls["llm"] == {"model": "test/model", "api_key": "test-key"}
    assert calls["task"] == "Structured worker packet"
    assert calls["conversation"]["workspace"] == str(tmp_path)
    assert calls["conversation"]["max_iteration_per_run"] == 7
    assert calls["conversation"]["persistence_dir"] == str(persistence_dir)
    assert calls["conversation"]["stuck_detection"] is True
    assert len(calls["conversation"]["callbacks"]) == 1
    # Full-component wiring: the agent gets the 6-tool set (incl. the sub-agent delegation
    # tool) + condenser + AgentOps system-prompt suffix + security analyzer.
    tool_names = [t.get("name") for t in calls["tools"]]
    assert tool_names == [
        "terminal",
        "file_editor",
        "task_tracker",
        "grep",
        "glob",
        "task_tool_set",
    ]
    assert "condenser" in calls["agent"]
    assert "security_analyzer" in calls["agent"]
    assert calls["agent_context"]["load_project_skills"] is True
    assert "AgentOps Harness" in calls["agent_context"]["system_message_suffix"]
    assert calls["condenser"] == {"llm": calls["agent"]["llm"], "max_size": 80, "keep_first": 4}
    # 04 sub-agents register, and with browser disabled to honor the no-network constraint.
    assert calls.get("builtins_registered") is True
    assert calls.get("builtins_enable_browser") is False
    assert events_path.exists()
    assert json.loads(events_path.read_text(encoding="utf-8")) == {
        "event": {"id": "event-1", "mode": "json", "source": "agent"},
        "event_type": "FakeEvent",
    }
    assert summary["event_log_path"] == str(events_path)
    assert summary["observable_event_count"] == 1


def test_runner_surfaces_summary_when_archetype_registration_fails(
    monkeypatch, tmp_path, capsys
) -> None:
    """A failure inside register_builtins_agents must still emit a summary + EXIT_RUN_ERROR.

    Regression for the case where archetype registration ran outside the guarded try block,
    so a broken preset / SDK mismatch would crash main() with no observable outcome.
    """
    calls: dict[str, object] = {}
    _install_fake_openhands(monkeypatch, calls, register_raises=True)

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "task"})())

    assert main() == 1  # EXIT_RUN_ERROR — caught and surfaced, not an uncaught crash
    summary = _summary_from_stdout(capsys.readouterr().out)
    assert summary["status"] == "failed"
    assert summary["termination_reason"] == "run_error"
    # The agent loop never started because registration failed first.
    assert "conversation" not in calls
