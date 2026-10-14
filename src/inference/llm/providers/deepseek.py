"""DeepSeek Chat Completions; JSON Output mode since the API has no strict JSON Schema."""

from typing import Any

from inference.llm.providers._chat_completions import ChatCompletionsProvider


class DeepSeekProvider(ChatCompletionsProvider):
    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        payload = super()._payload(messages, schema, schema_name, tokens)
        payload["max_tokens"] = payload.pop("max_completion_tokens")
        # Only json_object is supported: the schema is not sent, so the prompt must describe the
        # output (it must also contain the word "json"); the caller validates the schema afterwards.
        payload["response_format"] = {"type": "json_object"}
        # Thinking is on by default and ignores temperature; turn it off for latency and determinism.
        payload["thinking"] = {"type": "disabled"}
        return payload
