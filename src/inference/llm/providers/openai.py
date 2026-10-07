"""OpenAI Chat Completions with strict Structured Outputs."""

from typing import Any

from inference.llm.config import OpenAIConfig
from inference.llm.providers._chat_completions import ChatCompletionsProvider


class OpenAIProvider(ChatCompletionsProvider):
    _config: OpenAIConfig

    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        payload = {**super()._payload(messages, schema, schema_name, tokens), "store": False}
        payload["service_tier"] = self._config.service_tier
        # GPT-6 defaults to reasoning; custom temperature is rejected unless effort is none.
        if self.model.startswith("gpt-6-"):
            payload.pop("temperature", None)
            # Call-turn structured extraction is latency-sensitive. Luna and Sol
            # support no reasoning; Astra does not, so leave it at the default.
            if self.model.startswith(("gpt-6-luna", "gpt-6-sol")):
                payload["reasoning_effort"] = "none"
        return payload
