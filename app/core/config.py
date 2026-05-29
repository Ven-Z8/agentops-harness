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

    model_config = SettingsConfigDict(env_prefix="AGENTOPS_", env_file=".env", extra="ignore")


settings = Settings()
