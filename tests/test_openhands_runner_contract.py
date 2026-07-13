import json
import subprocess
import sys

import pytest

# OpenHands is a core dependency — the inner loop always runs the REAL SDK (no fakes).
# importorskip degrades gracefully only if someone strips the dependency.
pytest.importorskip("openhands.sdk")

from openhands.sdk import LLM  # noqa: E402

from app.core.packs.loader import load_pack  # noqa: E402
from app.core.workers.openhands_runner import build_agent  # noqa: E402

DUMMY_LLM = LLM(
    model="anthropic/claude-sonnet-4-5-20250929", api_key="sk-dummy-not-used", usage_id="t"
)


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


# --- Early-return guards (no SDK construction) -------------------------------------------


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


def test_runner_returns_sdk_missing_when_openhands_unavailable(monkeypatch) -> None:
    # Defensive guard: even though OpenHands is now a core dependency, the runner still
    # classifies a stripped install as setup_missing rather than crashing.
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
    monkeypatch.delenv("AGENTOPS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENTOPS_OPENROUTER_API_KEY", raising=False)

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", "."])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "Do work"})())

    assert main() == 3


def test_runner_returns_config_error_for_malformed_env() -> None:
    completed = _run_runner(task="Do work", env={"OPENHANDS_MAX_ITERATIONS": "bad"})

    assert completed.returncode == 6
    assert "OPENHANDS_MAX_ITERATIONS" in completed.stderr


# --- Real-SDK agent assembly (no mock, no network) ---------------------------------------


def test_build_agent_wires_full_component_set_against_real_sdk() -> None:
    """build_agent assembles a real OpenHands Agent with the 9-component wiring.

    Uses the REAL SDK (no fake module tree) and a dummy API key — construction makes no
    network call. Verifies our wiring survives the real SDK's actual constructor surface.
    """
    agent, tool_names, hooks = build_agent(DUMMY_LLM, None)

    assert tool_names == [
        "terminal", "file_editor", "task_tracker", "grep", "glob", "task_tool_set",
    ]
    assert len(agent.tools) == 6  # the real Agent exposes its tool set
    assert agent.condenser is not None  # 02 context management
    assert agent.agent_context is not None
    assert "AgentOps Harness" in (agent.agent_context.system_message_suffix or "")  # 03/07 bridge
    assert hooks == []


def test_build_agent_applies_capability_pack_against_real_sdk() -> None:
    """A capability pack narrows tools and extends the system suffix on the real Agent."""
    pack = load_pack("packs/example")
    agent, tool_names, hooks = build_agent(DUMMY_LLM, pack)

    # pack tools are a subset of the 6 built-ins
    assert set(tool_names).issubset(
        {"terminal", "file_editor", "task_tracker", "grep", "glob", "task_tool_set"}
    )
    assert len(agent.tools) == len(tool_names)
    assert pack.manifest.name in agent.agent_context.system_message_suffix


def test_runner_surfaces_summary_when_archetype_registration_fails(monkeypatch, tmp_path) -> None:
    """A failure during agent assembly still emits a summary + EXIT_RUN_ERROR (not a crash).

    Monkeypatches the REAL register_builtins_agents to raise; build_agent runs inside main()'s
    guarded try, so the failure is caught and surfaced rather than crashing main().
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def _boom(**_kwargs):
        raise RuntimeError("broken preset")

    monkeypatch.setattr("openhands.tools.preset.register_builtins_agents", _boom)
    monkeypatch.setattr(
        "app.core.workers.openhands_runner.openhands_sdk_available", lambda: True
    )
    monkeypatch.setenv("LLM_API_KEY", "sk-dummy-not-used")
    monkeypatch.setenv("OPENHANDS_MODEL", "anthropic/claude-sonnet-4-5-20250929")

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "task"})())

    assert main() == 1  # EXIT_RUN_ERROR — caught and surfaced
    # (summary is printed to stdout; the run did not crash)


def test_runner_passes_openrouter_transport_metadata_to_llm(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return object()

    def stop_after_llm(*_args, **_kwargs):
        raise RuntimeError("stop after llm construction")

    monkeypatch.setattr("app.core.workers.openhands_runner.openhands_sdk_available", lambda: True)
    monkeypatch.setattr("openhands.sdk.LLM", fake_llm)
    monkeypatch.setattr("app.core.workers.openhands_runner.build_agent", stop_after_llm)
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENTOPS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_BASE_URL", "https://router.example/v1")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_SITE_URL", "https://agentops.example")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_APP_TITLE", "AgentOps Portfolio")

    from app.core.workers.openhands_runner import main

    monkeypatch.setattr(sys, "argv", ["openhands_runner", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: "task"})())

    assert main() == 1
    assert captured == {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "api_key": "openrouter-secret",
        "base_url": "https://router.example/v1",
        "openrouter_site_url": "https://agentops.example",
        "openrouter_app_name": "AgentOps Portfolio",
    }
