import pytest
from typer.testing import CliRunner

from app.cli import app
from app.core.config import Settings
from app.core.llm import (
    MockLLMClient,
    OpenAICompatibleLLMClient,
    build_llm_client,
    build_runtime_llm_client,
    provider_status,
)


def test_build_llm_client_defaults_to_mock() -> None:
    client = build_llm_client(Settings(_env_file=None))

    assert isinstance(client, MockLLMClient)


def test_build_runtime_llm_client_returns_none_for_mock_provider() -> None:
    assert build_runtime_llm_client(Settings(llm_provider="mock")) is None


def test_build_llm_client_creates_openrouter_compatible_client() -> None:
    settings = Settings(
        llm_provider="openrouter",
        openrouter_api_key="test-key",
        openrouter_model="deepseek/deepseek-v4-flash",
        openrouter_site_url="https://example.com",
        openrouter_app_title="AgentOps Harness",
    )

    client = build_llm_client(settings)

    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client.model == "deepseek/deepseek-v4-flash"
    assert client.base_url == "https://openrouter.ai/api/v1"
    assert client.default_headers["HTTP-Referer"] == "https://example.com"
    assert client.default_headers["X-OpenRouter-Title"] == "AgentOps Harness"


def test_build_runtime_llm_client_returns_openrouter_client_when_enabled() -> None:
    client = build_runtime_llm_client(
        Settings(
            llm_provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="deepseek/deepseek-v4-flash",
        )
    )

    assert isinstance(client, OpenAICompatibleLLMClient)


def test_openrouter_provider_requires_api_key() -> None:
    settings = Settings(llm_provider="openrouter", openrouter_api_key=None)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_llm_client(settings)


def test_provider_status_reports_openrouter_readiness() -> None:
    status = provider_status(
        Settings(
            llm_provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="deepseek/deepseek-v4-flash",
        )
    )

    assert status["provider"] == "openrouter"
    assert status["configured"] is True
    assert status["model"] == "deepseek/deepseek-v4-flash"


def test_cli_provider_status_reports_mock_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.cli.settings.llm_provider", "mock")
    monkeypatch.setattr("app.cli.settings.openrouter_api_key", None)
    runner = CliRunner()

    result = runner.invoke(app, ["providers", "status"])

    assert result.exit_code == 0
    assert '"provider": "mock"' in result.stdout
