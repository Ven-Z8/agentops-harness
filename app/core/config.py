from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: str = "mock"
    run_storage: Path = Path(".agentops/runs.db")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str = "deepseek/deepseek-v4-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = None
    openrouter_app_title: str = "AgentOps Harness"

    # Obsidian Brain (VaultCodec)
    vault_url: str = "https://localhost:27124"
    vault_api_key: str = ""

    # AO-D01-01: configuration must be explicit and deterministic.
    # ``env_file`` is deliberately NOT set here: pydantic-settings would otherwise
    # silently read a CWD ``.env`` into every Settings() constructed in that
    # directory (tests, CI runs on machines with a developer .env, workers),
    # leaking ambient provider values into fields the caller never passed.
    # Ambient dotenv content must never change provider configuration.
    # Callers that want file-based config must pass ``_env_file=...`` explicitly
    # (see ``load_settings``) or export real environment variables.
    model_config = SettingsConfigDict(env_prefix="AGENTOPS_", extra="ignore")


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Build Settings, explicitly opting into a dotenv file.

    Resolution precedence (pydantic-settings): real environment variables beat
    dotenv values; dotenv values beat class defaults. Passing ``env_file=None``
    returns the ambient-environment-only Settings used by tests and CLI defaults.
    """
    return Settings(_env_file=env_file)


settings = load_settings()
