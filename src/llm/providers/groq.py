"""Groq Chat Completions; select a model supporting strict JSON Schema."""

from typing import Any

from llm.providers._chat_completions import ChatCompletionsProvider


class GroqProvider(ChatCompletionsProvider):
    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        payload = super()._payload(messages, schema, schema_name, tokens)
        if self.model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            payload["reasoning_effort"] = "low"
        return payload
