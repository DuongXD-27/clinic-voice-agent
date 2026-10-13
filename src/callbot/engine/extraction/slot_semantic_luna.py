"""Adapter Luna (OpenAI Structured Outputs) cho câu chọn khung — dự phòng của Jev (plan §4.11).

Cùng bộ nhãn và cùng kiểm sau model (`ground_slot_reading`) với adapter Jev; Luna không trả xác suất nên
`confident` luôn True, các cổng không dựa xác suất (`decides_now`, `KEEP_OLD` → A/B, span nguyên văn,
`PICK ≤ số khung`, `CONFIRM` không mở khóa ghi) vẫn áp ở `resolve_slot_act`.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from callbot.engine.extraction.model_budget import report_model_status
from callbot.engine.extraction.schema import compact_json_schema
from callbot.engine.extraction.slot_semantic import (
    SlotReading,
    SlotSemanticContext,
    ground_slot_reading,
)
from callbot.engine.extraction.text import normalize
from callbot.tracing.generation import finish_generation, generation_scope, normalized_result
from inference.common.telemetry import InferenceTimer
from inference.llm.gateway import LLMGateway
from inference.llm.prompt.slot_reply import PROMPT_VERSION, build_slot_messages

logger = logging.getLogger(__name__)

_ACT_VALUES = Literal[
    "AMBIGUOUS",
    "PICK",
    "TIME",
    "MORE",
    "ANY",
    "REFUSE",
    "KEEP_OLD",
    "CONFIRM",
    "CANCEL",
    "OUT_OF_SCOPE",
    "QUESTION",
]


class SlotReplyReading(BaseModel):
    """Schema đóng cho Structured Outputs: không có `slot_id`, giờ chuẩn hóa hay quyền ghi."""

    model_config = ConfigDict(json_schema_extra=compact_json_schema, strict=True, extra="forbid")

    act: _ACT_VALUES
    pick: int | None
    wanted_time_span: str | None
    decides_now: bool
    intent: Literal["CANCEL", "OUT_OF_SCOPE"] | None
    clinical: Literal["EMERGENCY", "ADVICE_REQUEST", "MENTION"] | None
    clinical_span: str | None


class LunaSlotSemanticExtractor:
    """Một request cho lượt; mọi lỗi trả `None` để lượt giữ kết quả luật."""

    def __init__(self, gateway: LLMGateway, *, max_completion_tokens: int) -> None:
        self._gateway = gateway
        self._max_completion_tokens = max_completion_tokens
        self.last_status: Optional[str] = None

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    def analyze(self, context: SlotSemanticContext) -> Optional[SlotReading]:
        timer = InferenceTimer()
        status = "invalid_response"
        reply = None
        try:
            if not normalize(context.transcript):
                status = "empty"
                return None
            status = "error"
            with generation_scope("llm.slot_semantic_extract") as generation:
                try:
                    reply = self._gateway.generate_structured(
                        build_slot_messages(context),
                        schema=SlotReplyReading.model_json_schema(),
                        schema_name=PROMPT_VERSION,
                        max_completion_tokens=self._max_completion_tokens,
                    )
                    if reply.status != "completed" or reply.content is None:
                        status = reply.status
                        return None
                    status = "invalid_response"
                    parsed = SlotReplyReading.model_validate_json(reply.content)
                    reading = ground_slot_reading(
                        SlotReading(
                            act=parsed.act,
                            confident=True,
                            decides_now=parsed.decides_now,
                            pick=parsed.pick,
                            wanted_span=parsed.wanted_time_span,
                            intent=parsed.intent,
                            clinical=parsed.clinical,
                            clinical_span=parsed.clinical_span,
                        ),
                        context,
                    )
                    status = "accepted" if reading is not None else "rejected"
                    return reading
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
            self.last_status = status
            report_model_status(status)
            logger.info(
                "Slot semantic: %s",
                status,
                extra={
                    "semantic_provider": self._gateway.provider_name,
                    "semantic_model": self._gateway.model,
                    "semantic_prompt_version": PROMPT_VERSION,
                    "semantic_route_reason": context.route_reason,
                    "semantic_question_id": context.question_id.value,
                    "semantic_status": status,
                    "semantic_elapsed_ms": timer.elapsed_ms,
                },
            )
        return None
