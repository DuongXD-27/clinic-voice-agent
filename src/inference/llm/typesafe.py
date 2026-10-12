"""TypeSafe System One (Jev) qua HTTP — `POST /v1/systemone`, độc lập với kiểu dữ liệu callbot.

Không dùng SDK `typesafe-sdk`: SDK tự retry và không có deadline tổng. Ở đây giống các provider
LLM khác: một request, không retry, trần cứng `MODEL_CALL_HARD_LIMIT_S` tới khi nhận đủ body.

Hỗ trợ Choice và Noul — tầng ngữ nghĩa không cần Score. Trường của `SystemOneReply`
đặt tên giống `StructuredReply` để `finish_generation` đọc được token, model, HTTP status.
"""

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inference.common.transport import (
    MODEL_CALL_HARD_LIMIT_S,
    HttpClientFactory,
    TotalRequestTimeout,
    build_http_timeout,
    post_with_total_timeout,
)
from inference.llm.config import TypeSafeConfig
from inference.llm.providers.base import ReplyStatus

# Giới hạn của API cho một câu Choice
MAX_CHOICE_OPTIONS = 255

# Mô tả option / instructions: chuỗi, object hoặc mảng JSON (None = chỉ tên option)
Criterion = Optional[str | dict[str, Any] | list[Any]]


@dataclass(frozen=True)
class ChoiceQuestion:
    instructions: str | dict[str, Any]
    criteria: dict[str, Criterion]

    def payload(self) -> dict[str, Any]:
        if not 2 <= len(self.criteria) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"Choice cần 2..{MAX_CHOICE_OPTIONS} option, có {len(self.criteria)}")
        return {"type": "choice", "instructions": self.instructions, "criteria": self.criteria}


@dataclass(frozen=True)
class NoulQuestion:
    """Có / không. `criteria` (tuỳ chọn) định nghĩa nghĩa của `true` (gần 1) và `false` (gần 0)."""

    instructions: str | dict[str, Any]
    true: Criterion = None
    false: Criterion = None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": "noul", "instructions": self.instructions}
        criteria = {k: v for k, v in (("true", self.true), ("false", self.false)) if v is not None}
        if criteria:
            payload["criteria"] = criteria
        return payload


Question = ChoiceQuestion | NoulQuestion


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    type: Literal["choice"]
    choice: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]


class NoulAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    type: Literal["noul"]
    # Xác suất "có"; Noul không có trường confidence
    noul: float = Field(ge=0, le=1)


Answer = Annotated[Union[ChoiceAnswer, NoulAnswer], Field(discriminator="type")]


class _Usage(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    model: str | None = None
    answers: dict[str, Answer]
    usage: _Usage | None = None


@dataclass(frozen=True)
class SystemOneReply:
    status: ReplyStatus
    answers: dict[str, ChoiceAnswer | NoulAnswer] = field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    actual_model: str | None = None
    provider_request_id: str | None = None
    http_status: int | None = None
    model_call_latency_ms: float | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


class TypeSafeClient:
    def __init__(
        self, config: TypeSafeConfig, *, client_factory: HttpClientFactory | None = None
    ) -> None:
        self._config = config
        self._timeout = build_http_timeout(
            min(MODEL_CALL_HARD_LIMIT_S, config.timeout_s), min(1.0, config.connect_timeout_s)
        )
        self._client_factory = client_factory or httpx.Client

    provider_name = "typesafe"

    @property
    def model(self) -> str:
        return self._config.model

    def evaluate(self, state: Any, questions: dict[str, Question]) -> SystemOneReply:
        """Mọi câu hỏi trong MỘT request. Thiếu câu trả lời nào -> `invalid_response`."""
        payload = {
            "model": self.model,
            "state": state,
            "questions": {name: question.payload() for name, question in questions.items()},
        }
        timed = None
        try:
            timed = post_with_total_timeout(
                self._client_factory,
                total_timeout_s=min(self._config.timeout_s, MODEL_CALL_HARD_LIMIT_S),
                url=self._config.endpoint,
                headers={"Authorization": f"Bearer {self._config.api_key.get_secret_value()}"},
                timeout=self._timeout,
                json=payload,
            )
            response = timed.response
            response.raise_for_status()
            parsed = _Response.model_validate_json(response.content)
            complete = all(
                _answers(question, parsed.answers.get(name)) for name, question in questions.items()
            )
            return SystemOneReply(
                status="completed" if complete else "invalid_response",
                answers=parsed.answers if complete else {},
                prompt_tokens=parsed.usage.input_tokens if parsed.usage else None,
                completion_tokens=parsed.usage.output_tokens if parsed.usage else None,
                actual_model=parsed.model,
                provider_request_id=response.headers.get("x-typesafe-request-id"),
                http_status=response.status_code,
                model_call_latency_ms=timed.model_call_latency_ms,
            )
        except (httpx.TimeoutException, TotalRequestTimeout):
            return SystemOneReply("timeout")
        except httpx.HTTPStatusError as exc:
            return SystemOneReply(
                "http_error",
                http_status=exc.response.status_code,
                model_call_latency_ms=timed.model_call_latency_ms if timed else None,
            )
        except httpx.RequestError:
            return SystemOneReply("network_error")
        except ValidationError:
            return SystemOneReply(
                "invalid_response",
                model_call_latency_ms=timed.model_call_latency_ms if timed else None,
            )


def _answers(question: Question, answer: ChoiceAnswer | NoulAnswer | None) -> bool:
    """Câu trả lời đúng kiểu câu hỏi; Choice phải là một option đã gửi."""
    if isinstance(question, ChoiceQuestion):
        return isinstance(answer, ChoiceAnswer) and answer.choice in question.criteria
    return isinstance(answer, NoulAnswer)
