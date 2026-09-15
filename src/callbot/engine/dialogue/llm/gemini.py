from typing import Any, Optional

from callbot.engine.dialogue.llm.base import LLMReply


class GeminiLLM:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai  # pip install -e ".[llm]"

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        json_mode: bool = False,
    ) -> LLMReply:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
        )
        # TODO: map `tools` sang function declarations; parse function_call -> ToolCall
        contents = [
            types.Content(
                role="model" if m["role"] == "bot" else "user", parts=[types.Part(text=m["text"])]
            )
            for m in messages
        ]
        response = self._get_client().models.generate_content(
            model=self._model, contents=contents, config=config
        )
        usage = response.usage_metadata
        return LLMReply(
            text=response.text or "",
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )
