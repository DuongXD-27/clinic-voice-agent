"""Synchronous Structured Outputs transport, independent of callbot domain types."""

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inference.common.transport import HttpClientFactory, build_http_timeout
from inference.llm.config import ProviderConfig
from inference.llm.providers.base import ReplyStatus, StructuredReply


class _Message(BaseModel):
    model_config = ConfigDict(strict=True)
    content: str | None = None
    refusal: str | None = None


class _Choice(BaseModel):
    model_config = ConfigDict(strict=True)
    finish_reason: str
    message: _Message


class _Usage(BaseModel):
    model_config = ConfigDict(strict=True)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _Completion(BaseModel):
    model_config = ConfigDict(strict=True)
    choices: list[_Choice] = Field(min_length=1, max_length=1)
    usage: _Usage | None = None


class ChatCompletionsProvider:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._config = config
        self._timeout = build_http_timeout(config.timeout_s, config.connect_timeout_s)
        self._client_factory = client_factory or httpx.Client

    @property
    def model(self) -> str:
        return self._config.model

    def _payload(
        self, messages: list[dict[str, str]], schema: dict[str, Any], schema_name: str, tokens: int
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": 0,
            "max_completion_tokens": tokens,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
        max_completion_tokens: int = 200,
    ) -> StructuredReply:
        try:
            # One request, no retries; close the client even for HTTP/parsing failures.
            with self._client_factory() as client:
                response = client.post(
                    self._config.endpoint,
                    headers={"Authorization": f"Bearer {self._config.api_key.get_secret_value()}"},
                    timeout=self._timeout,
                    json=self._payload(messages, schema, schema_name, max_completion_tokens),
                )
                response.raise_for_status()
                completion = _Completion.model_validate_json(response.content)
            choice = completion.choices[0]
            status: ReplyStatus = "completed"
            if choice.message.refusal is not None:
                status = "refusal"
            elif choice.finish_reason != "stop":
                status = "incomplete"
            elif choice.message.content is None:
                status = "invalid_response"
            usage = completion.usage
            return StructuredReply(
                status=status,
                content=choice.message.content if status == "completed" else None,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
        except httpx.TimeoutException:
            return StructuredReply("timeout")
        except httpx.HTTPStatusError:
            return StructuredReply("http_error")
        except httpx.RequestError:
            return StructuredReply("network_error")
        except ValidationError:
            return StructuredReply("invalid_response")
