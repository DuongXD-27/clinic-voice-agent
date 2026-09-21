"""OpenAI Chat Completions with strict Structured Outputs."""

from typing import Any

from inference.llm.providers._chat_completions import ChatCompletionsProvider


class OpenAIProvider(ChatCompletionsProvider):
    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        return {**super()._payload(messages, schema, schema_name, tokens), "store": False}
