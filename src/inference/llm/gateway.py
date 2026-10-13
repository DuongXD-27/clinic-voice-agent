"""Single entry point for configured LLM calls; no implicit retries or failover."""

import json
from dataclasses import replace
from typing import Any

from inference.common.errors import UnsupportedProviderError
from inference.common.transport import HttpClientFactory
from inference.llm.config import (
    DeepSeekConfig,
    GeminiConfig,
    GroqConfig,
    OpenAIConfig,
    OpenRouterConfig,
    ProviderConfig,
)
from inference.llm.providers.base import ProviderName, StructuredProvider, StructuredReply
from inference.llm.providers.deepseek import DeepSeekProvider
from inference.llm.providers.gemini import GeminiProvider
from inference.llm.providers.groq import GroqProvider
from inference.llm.providers.openai import OpenAIProvider
from inference.llm.providers.openrouter import OpenRouterProvider

PROVIDERS: dict[str, tuple[type[ProviderConfig], type[StructuredProvider]]] = {
    "openai": (OpenAIConfig, OpenAIProvider),
    "gemini": (GeminiConfig, GeminiProvider),
    "groq": (GroqConfig, GroqProvider),
    "openrouter": (OpenRouterConfig, OpenRouterProvider),
    "deepseek": (DeepSeekConfig, DeepSeekProvider),
}


def provider_config_type(provider_name: ProviderName) -> type[ProviderConfig]:
    if provider_name not in PROVIDERS:
        raise UnsupportedProviderError("LLM", provider_name)
    return PROVIDERS[provider_name][0]


class LLMGateway:
    def __init__(
        self,
        provider: StructuredProvider,
        *,
        provider_name: ProviderName,
        max_completion_tokens: int = 200,
    ) -> None:
        if max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be positive")
        self._provider = provider
        self.provider_name = provider_name
        self._max_completion_tokens = max_completion_tokens

    @property
    def model(self) -> str:
        return self._provider.model

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
        max_completion_tokens: int | None = None,
    ) -> StructuredReply:
        tokens = (
            self._max_completion_tokens if max_completion_tokens is None else max_completion_tokens
        )
        if tokens <= 0:
            raise ValueError("max_completion_tokens must be positive")
        if not messages or any(
            message.get("role") not in {"system", "user", "assistant"}
            or not isinstance(message.get("content"), str)
            for message in messages
        ):
            raise ValueError("Expected text messages with system/user/assistant roles")
        reply = self._provider.generate_structured(
            messages, schema=schema, schema_name=schema_name, max_completion_tokens=tokens
        )
        if reply.status == "completed":
            try:
                json.loads(reply.content or "")
            except (ValueError, TypeError):
                return replace(reply, status="invalid_response", content=None)
        return reply


def create_gateway(
    provider_name: ProviderName,
    *,
    config: ProviderConfig | None = None,
    client_factory: HttpClientFactory | None = None,
) -> LLMGateway:
    config_type = provider_config_type(provider_name)
    provider_type = PROVIDERS[provider_name][1]
    if config is not None and not isinstance(config, config_type):
        raise ValueError("Configuration does not match the selected provider")
    selected_config = config if config is not None else config_type()
    provider = provider_type(selected_config, client_factory=client_factory)
    return LLMGateway(
        provider,
        provider_name=provider_name,
        max_completion_tokens=selected_config.max_completion_tokens,
    )
