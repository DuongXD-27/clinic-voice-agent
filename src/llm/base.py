"""Provider-neutral contract used by the LLM gateway."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

ProviderName = Literal["openai", "gemini", "groq", "openrouter"]
ReplyStatus = Literal[
    "completed",
    "refusal",
    "incomplete",
    "invalid_response",
    "timeout",
    "http_error",
    "network_error",
]


@dataclass(frozen=True)
class StructuredReply:
    status: ReplyStatus
    content: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class StructuredProvider(Protocol):
    @property
    def model(self) -> str: ...

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any],
        schema_name: str,
        max_completion_tokens: int = 200,
    ) -> StructuredReply: ...
