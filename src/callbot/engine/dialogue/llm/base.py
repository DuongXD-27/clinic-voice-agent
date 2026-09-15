from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        json_mode: bool = False,
    ) -> LLMReply: ...
