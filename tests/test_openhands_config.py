import importlib.util

from app.core.config import Settings
from app.core.workers import openhands_config
from app.core.workers.openhands_config import (
    DEFAULT_OPENHANDS_MODEL,
    OPENHANDS_TOOL_NAMES,
    load_openhands_config,
    openhands_sdk_available,
)


def test_openhands_config_prefers_model_and_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENHANDS_MODEL", "openai/gpt-test")
    monkeypatch.setenv("OPENHANDS_MAX_ITERATIONS", "12")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    config = load_openhands_config()

    assert config.model == "openai/gpt-test"
    assert config.api_key_env == "OPENAI_API_KEY"
    assert config.max_iterations == 12
    assert config.tools == list(OPENHANDS_TOOL_NAMES)


def test_openhands_config_uses_agentops_openrouter_over_ambient_anthropic(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic")
    monkeypatch.setenv("AGENTOPS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_MODEL", "openrouter/openai/gpt-4.1")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_BASE_URL", "https://router.example/v1")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_SITE_URL", "https://agentops.example")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_APP_TITLE", "AgentOps Portfolio")

    config = load_openhands_config()

    assert config.model == "openrouter/openai/gpt-4.1"
    assert config.api_key_env == "AGENTOPS_OPENROUTER_API_KEY"
    assert config.base_url == "https://router.example/v1"
    assert config.openrouter_site_url == "https://agentops.example"
    assert config.openrouter_app_name == "AgentOps Portfolio"
    assert "openrouter-secret" not in config.model_dump_json()


def test_openhands_config_preserves_explicit_worker_override(monkeypatch) -> None:
    monkeypatch.setenv("OPENHANDS_MODEL", "openai/gpt-test")
    monkeypatch.setenv("LLM_API_KEY", "direct-worker-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic")
    monkeypatch.setenv("AGENTOPS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("AGENTOPS_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")

    config = load_openhands_config()

    assert config.model == "openai/gpt-test"
    assert config.api_key_env == "LLM_API_KEY"
    assert config.base_url is None
    assert config.openrouter_site_url is None
    assert config.openrouter_app_name is None


def test_openhands_config_uses_safe_default_without_auth(monkeypatch) -> None:
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    monkeypatch.delenv("OPENHANDS_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENTOPS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENTOPS_OPENROUTER_API_KEY", raising=False)

    config = load_openhands_config()

    assert config.model == DEFAULT_OPENHANDS_MODEL
    assert config.api_key_env is None
    assert config.max_iterations is None
    assert config.missing_auth


def test_openhands_config_rejects_invalid_max_iterations(monkeypatch) -> None:
    monkeypatch.setenv("OPENHANDS_MAX_ITERATIONS", "not-an-int")

    config = load_openhands_config()

    assert config.config_error == "OPENHANDS_MAX_ITERATIONS must be a positive integer."


def test_openhands_sdk_available_uses_importlib_spec(monkeypatch) -> None:
    def fake_find_spec(name: str):
        return object() if name in {"openhands.sdk", "openhands.tools.terminal"} else None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    assert openhands_sdk_available()


def test_live_auth_detects_openrouter_loaded_from_project_settings(monkeypatch) -> None:
    for name in (
        "LLM_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "AGENTOPS_LLM_PROVIDER",
        "AGENTOPS_OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    project_settings = Settings(
        _env_file=None,
        llm_provider="openrouter",
        openrouter_api_key="project-env-secret",
    )

    assert openhands_config.auth_available(project_settings) is True
