from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.core.config import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMClient(Protocol):
    def generate_text(self, prompt: str) -> str:
        """Generate unstructured text."""

    def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Generate output validated by a Pydantic schema."""


class MockLLMClient:
    def generate_text(self, prompt: str) -> str:
        return f"Mock response for: {prompt[:120]}"

    def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        raise NotImplementedError(
            "Mock structured generation is handled by deterministic agents in Phase 1."
        )


@dataclass(frozen=True)
class OpenAICompatibleLLMClient:
    api_key: str
    model: str
    base_url: str | None = None
    default_headers: dict[str, str] = field(default_factory=dict)

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=self.default_headers or None,
        )

    def generate_text(self, prompt: str) -> str:
        response = self._client().chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        return content or ""

    def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        response = self._client().chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty structured response")
        return schema.model_validate(json.loads(content))


def build_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()

    if provider == "mock":
        return MockLLMClient()

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("AGENTOPS_OPENROUTER_API_KEY is required for openrouter provider")
        headers = {
            "X-OpenRouter-Title": settings.openrouter_app_title,
        }
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        return OpenAICompatibleLLMClient(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            default_headers=headers,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("AGENTOPS_OPENAI_API_KEY is required for openai provider")
        return OpenAICompatibleLLMClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def build_runtime_llm_client(settings: Settings) -> LLMClient | None:
    if settings.llm_provider.lower() == "mock":
        return None
    return build_llm_client(settings)


def provider_status(settings: Settings) -> dict[str, str | bool | None]:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return {
            "provider": "mock",
            "configured": True,
            "model": None,
            "base_url": None,
        }
    if provider == "openrouter":
        return {
            "provider": "openrouter",
            "configured": bool(settings.openrouter_api_key),
            "model": settings.openrouter_model,
            "base_url": settings.openrouter_base_url,
        }
    if provider == "openai":
        return {
            "provider": "openai",
            "configured": bool(settings.openai_api_key),
            "model": settings.openai_model,
            "base_url": settings.openai_base_url,
        }
    return {
        "provider": provider,
        "configured": False,
        "model": None,
        "base_url": None,
    }
