from __future__ import annotations

import importlib.util
import os

from pydantic import BaseModel, Field

DEFAULT_OPENHANDS_MODEL = "anthropic/claude-sonnet-4-5-20250929"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_APP_NAME = "AgentOps Harness"
DEFAULT_OPENHANDS_TIMEOUT_SECONDS = 300
OPENHANDS_TOOL_NAMES = (
    "terminal",
    "file_editor",
    "task_tracker",
    "grep",
    "glob",
    "task_tool_set",  # 04 sub-agent delegation
)
AUTH_ENV_NAMES = ("LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


class OpenHandsConfig(BaseModel):
    model: str = DEFAULT_OPENHANDS_MODEL
    api_key_env: str | None = None
    base_url: str | None = None
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None
    max_iterations: int | None = None
    timeout_seconds: int = DEFAULT_OPENHANDS_TIMEOUT_SECONDS
    tools: list[str] = Field(default_factory=lambda: list(OPENHANDS_TOOL_NAMES))
    config_error: str | None = None

    @property
    def missing_auth(self) -> bool:
        return self.api_key_env is None


def _positive_int_env(name: str) -> tuple[int | None, str | None]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None, None
    try:
        value = int(raw)
    except ValueError:
        return None, f"{name} must be a positive integer."
    if value <= 0:
        return None, f"{name} must be a positive integer."
    return value, None


def _first_auth_env() -> str | None:
    for name in AUTH_ENV_NAMES:
        if os.getenv(name):
            return name
    return None


def _openrouter_model(model: str) -> str:
    route = model.strip()
    while route.startswith("openrouter/"):
        route = route.removeprefix("openrouter/")
    return f"openrouter/{route}"


def load_openhands_config() -> OpenHandsConfig:
    max_iterations, config_error = _positive_int_env("OPENHANDS_MAX_ITERATIONS")
    explicit_worker_override = bool(os.getenv("OPENHANDS_MODEL") or os.getenv("LLM_API_KEY"))
    openrouter_selected = (
        os.getenv("AGENTOPS_LLM_PROVIDER", "").strip().lower() == "openrouter"
        and bool(os.getenv("AGENTOPS_OPENROUTER_API_KEY"))
    )
    if openrouter_selected and not explicit_worker_override:
        return OpenHandsConfig(
            model=_openrouter_model(
                os.getenv("AGENTOPS_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
            ),
            api_key_env="AGENTOPS_OPENROUTER_API_KEY",
            base_url=os.getenv(
                "AGENTOPS_OPENROUTER_BASE_URL",
                DEFAULT_OPENROUTER_BASE_URL,
            ),
            openrouter_site_url=os.getenv("AGENTOPS_OPENROUTER_SITE_URL") or None,
            openrouter_app_name=os.getenv(
                "AGENTOPS_OPENROUTER_APP_TITLE",
                DEFAULT_OPENROUTER_APP_NAME,
            ),
            max_iterations=max_iterations,
            tools=list(OPENHANDS_TOOL_NAMES),
            config_error=config_error,
        )
    return OpenHandsConfig(
        model=os.getenv("OPENHANDS_MODEL", DEFAULT_OPENHANDS_MODEL),
        api_key_env=_first_auth_env(),
        max_iterations=max_iterations,
        tools=list(OPENHANDS_TOOL_NAMES),
        config_error=config_error,
    )


def openhands_sdk_available() -> bool:
    try:
        return (
            importlib.util.find_spec("openhands.sdk") is not None
            and importlib.util.find_spec("openhands.tools.terminal") is not None
        )
    except ModuleNotFoundError:
        return False
