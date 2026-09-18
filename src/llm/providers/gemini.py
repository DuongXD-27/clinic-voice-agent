"""Gemini native generateContent transport with JSON Schema output."""

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm.base import ReplyStatus, StructuredReply
from llm.config import GeminiConfig


class _Part(BaseModel):
    model_config = ConfigDict(strict=True)
    text: str | None = None
    thought: bool = False


class _Content(BaseModel):
    model_config = ConfigDict(strict=True)
    parts: list[_Part] = Field(default_factory=list)


class _Candidate(BaseModel):
    model_config = ConfigDict(strict=True)
    content: _Content | None = None
    finishReason: str | None = None


class _Feedback(BaseModel):
    model_config = ConfigDict(strict=True)
    blockReason: str | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(strict=True)
    promptTokenCount: int | None = Field(default=None, ge=0)
    candidatesTokenCount: int | None = Field(default=None, ge=0)
    thoughtsTokenCount: int = Field(default=0, ge=0)


class _Response(BaseModel):
    model_config = ConfigDict(strict=True)
    candidates: list[_Candidate] = Field(default_factory=list, max_length=1)
    promptFeedback: _Feedback | None = None
    usageMetadata: _Usage | None = None


class GeminiProvider:
    def __init__(
        self, config: GeminiConfig, *, client_factory: Callable[[], httpx.Client] | None = None
    ) -> None:
        self._config = config
        self._client_factory = client_factory or httpx.Client
        self._timeout = httpx.Timeout(config.timeout_s, connect=config.connect_timeout_s)

    @property
    def model(self) -> str:
        return self._config.model

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
        max_completion_tokens: int = 200,
    ) -> StructuredReply:
        system = []
        contents = []
        for message in messages:
            if message["role"] == "system":
                system.append({"text": message["content"]})
            elif message["role"] in {"user", "assistant"}:
                contents.append(
                    {
                        "role": "model" if message["role"] == "assistant" else "user",
                        "parts": [{"text": message["content"]}],
                    }
                )
            else:
                raise ValueError("Unsupported message role")
        generation = {
            "temperature": 0,
            "maxOutputTokens": max_completion_tokens,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        }
        model = self.model.removeprefix("models/")
        if model in {"gemini-2.5-flash", "gemini-2.5-flash-lite"}:
            generation["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": system}
        try:
            with self._client_factory() as client:
                response = client.post(
                    f"{self._config.endpoint}/{quote(model, safe='')}:generateContent",
                    headers={"x-goog-api-key": self._config.api_key.get_secret_value()},
                    timeout=self._timeout,
                    json=payload,
                )
                response.raise_for_status()
                result = _Response.model_validate_json(response.content)
            status: ReplyStatus = "invalid_response"
            text = None
            if result.promptFeedback and result.promptFeedback.blockReason not in {
                None,
                "BLOCK_REASON_UNSPECIFIED",
            }:
                status = "refusal"
            elif result.candidates:
                candidate = result.candidates[0]
                if candidate.finishReason in {
                    "SAFETY",
                    "RECITATION",
                    "BLOCKLIST",
                    "PROHIBITED_CONTENT",
                    "SPII",
                    "IMAGE_SAFETY",
                }:
                    status = "refusal"
                elif candidate.finishReason == "STOP" and candidate.content:
                    text = "".join(
                        part.text or "" for part in candidate.content.parts if not part.thought
                    )
                    status = "completed" if text else "invalid_response"
                elif candidate.finishReason and candidate.finishReason != "STOP":
                    status = "incomplete"
            usage = result.usageMetadata
            return StructuredReply(
                status,
                text if status == "completed" else None,
                usage.promptTokenCount if usage else None,
                (usage.candidatesTokenCount + usage.thoughtsTokenCount)
                if usage and usage.candidatesTokenCount is not None
                else None,
            )
        except httpx.TimeoutException:
            return StructuredReply("timeout")
        except httpx.HTTPStatusError:
            return StructuredReply("http_error")
        except httpx.RequestError:
            return StructuredReply("network_error")
        except ValidationError:
            return StructuredReply("invalid_response")
