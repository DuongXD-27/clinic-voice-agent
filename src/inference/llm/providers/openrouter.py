"""OpenRouter routes only to endpoints supporting the requested parameters."""

from typing import Any

from inference.llm.providers._chat_completions import ChatCompletionsProvider


class OpenRouterProvider(ChatCompletionsProvider):
    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        payload = super()._payload(messages, schema, schema_name, tokens)
        payload["max_tokens"] = payload.pop("max_completion_tokens")
        payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
        return payload
