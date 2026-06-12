import importlib.util

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


def test_openhands_config_uses_safe_default_without_auth(monkeypatch) -> None:
    monkeypatch.delenv("OPENHANDS_MODEL", raising=False)
    monkeypatch.delenv("OPENHANDS_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

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
