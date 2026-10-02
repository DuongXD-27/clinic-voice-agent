"""Name slot filling fallback: send the pending bot question with the caller answer, then
ground and normalize the provider result into a SlotFillingResult.

The bot question is context only; the name and its span must come from the caller answer.
"""

import logging
from typing import Optional, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from callbot.engine.extraction.fallback import (
    SlotFillingResult,
    SlotFillingStatus,
    guard_fallback,
)
from callbot.engine.extraction.full_name import valid_name_span
from callbot.engine.extraction.schema import Field, Intent, Provenance, QuestionId
from callbot.engine.extraction.text import clean
from callbot.tracing.generation import finish_generation, generation_scope, normalized_result
from inference.common.telemetry import InferenceTimer
from inference.llm.gateway import LLMGateway
from inference.llm.prompt.name_slot_filling import PROMPT_VERSION, build_messages
from inference.llm.providers.base import StructuredReply

logger = logging.getLogger(__name__)


class NameExtraction(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    full_name: str | None
    span: str | None

    @model_validator(mode="after")
    def paired_fields(self) -> Self:
        if (self.full_name is None) != (self.span is None):
            raise ValueError("Name and span must both be null or both be strings")
        return self


class NameSlotFiller:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def intent(self, transcript: str, allowed: frozenset[Intent]) -> None:
        return None

    def agreement(self, transcript: str, question_id: QuestionId) -> None:
        return None

    def full_name(
        self,
        transcript: str,
        *,
        question_id: QuestionId = QuestionId.ASK_NAME,
        bot_question: Optional[str] = None,
    ) -> SlotFillingResult:
        timer = InferenceTimer()
        status = "invalid_response"
        field: Field[str] = Field.nothing()
        reply = None
        try:
            if question_id is not QuestionId.ASK_NAME:
                status, field = "skipped_question", Field.skipped()
            elif not clean(transcript):
                status = "empty"
            else:
                messages = build_messages(
                    transcript,
                    question_id=question_id.value,
                    # ASK_NAME thiếu nội dung câu hỏi: gửi null, không dựng lại lời bot chưa nói
                    bot_question=(bot_question or "").strip() or None,
                )
                schema = NameExtraction.model_json_schema()
                status = "error"
                with generation_scope("llm.name_slot_fill") as generation:
                    try:
                        reply = self._gateway.generate_structured(
                            messages,
                            schema=schema,
                            schema_name=PROMPT_VERSION,
                        )
                        status = "invalid_response"
                        status, field = _ground(reply, transcript)
                    finally:
                        finish_generation(
                            generation,
                            self._gateway.provider_name,
                            self._gateway.model,
                            reply,
                            normalized_result(status),
                        )
        except ValidationError:
            status = "invalid_response"
        finally:
            elapsed_ms = timer.elapsed_ms
            # Never log exception text, response bodies, names, transcripts, bot questions,
            # or credentials.
            logger.info(
                "Name slot filling fallback: %s",
                status,
                extra={
                    "slot_filling_provider": self._gateway.provider_name,
                    "slot_filling_model": self._gateway.model,
                    "slot_filling_prompt_version": PROMPT_VERSION,
                    "slot_filling_question_id": question_id.value,
                    "slot_filling_has_bot_question": bool((bot_question or "").strip()),
                    "slot_filling_status": status,
                    "slot_filling_elapsed_ms": elapsed_ms,
                    "slot_filling_prompt_tokens": reply.prompt_tokens if reply else None,
                    "slot_filling_completion_tokens": reply.completion_tokens if reply else None,
                },
            )
        return SlotFillingResult(_OUTCOMES.get(status, _UNAVAILABLE), field, elapsed_ms)


# Trạng thái chi tiết (log) -> kết cục cho người gọi. Mọi trạng thái khác (timeout, refusal,
# incomplete, invalid_response, ...) là mô hình không trả lời được.
_UNAVAILABLE = SlotFillingStatus.UNAVAILABLE
_OUTCOMES = {
    "accepted": SlotFillingStatus.ACCEPTED,
    "no_name": SlotFillingStatus.NO_NAME,
    "rejected": SlotFillingStatus.REJECTED,
}


def _ground(reply: StructuredReply, transcript: str) -> tuple[str, Field[str]]:
    """Trạng thái chi tiết và tên đã qua guard; ném ValidationError khi nội dung sai schema."""
    if reply.status != "completed" or reply.content is None:
        return reply.status, Field.nothing()
    result = NameExtraction.model_validate_json(reply.content)
    if result.full_name is None:
        return "no_name", Field.nothing()
    name, span = clean(result.full_name), clean(result.span or "")
    if name != span or not valid_name_span(name):
        return "rejected", Field.nothing()
    guarded = guard_fallback(Field(name, Provenance.FALLBACK, span), transcript, None)
    return ("accepted" if guarded.found else "rejected"), guarded
