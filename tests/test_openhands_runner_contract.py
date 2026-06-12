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

    sdk = ModuleType("openhands.sdk")
    sdk.LLM = FakeLLM
    sdk.Agent = FakeAgent
    sdk.Conversation = FakeConversation
    sdk.Tool = FakeTool

    terminal = ModuleType("openhands.tools.terminal")
    terminal.TerminalTool = type("TerminalTool", (), {"name": "terminal"})
    file_editor = ModuleType("openhands.tools.file_editor")
    file_editor.FileEditorTool = type("FileEditorTool", (), {"name": "file_editor"})

    monkeypatch.setitem(sys.modules, "openhands", ModuleType("openhands"))
    monkeypatch.setitem(sys.modules, "openhands.sdk", sdk)
    monkeypatch.setitem(sys.modules, "openhands.tools", ModuleType("openhands.tools"))
    monkeypatch.setitem(sys.modules, "openhands.tools.terminal", terminal)
    monkeypatch.setitem(sys.modules, "openhands.tools.file_editor", file_editor)
    monkeypatch.setattr(
        "app.core.workers.openhands_runner.openhands_sdk_available",
        lambda: True,
    )
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENHANDS_MODEL", "test/model")
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
    assert len(calls["conversation"]["callbacks"]) == 1
    assert events_path.exists()
    assert json.loads(events_path.read_text(encoding="utf-8")) == {
        "event": {"id": "event-1", "mode": "json", "source": "agent"},
        "event_type": "FakeEvent",
    }
    assert summary["event_log_path"] == str(events_path)
    assert summary["observable_event_count"] == 1
