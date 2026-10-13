"""Tầng ngữ nghĩa dùng Structured Outputs — plan `docs/plans/t05-cancel-dialogue.md` §8.

Luật đọc từ khóa không thấy được ranh giới mệnh đề: "tôi không đủ tiền" thành REFUSE, "không, hủy đi"
thành "không hủy". Tầng này phân loại LẠI câu trong ngữ cảnh câu hỏi đang chờ, cho đúng một lần gọi
model mỗi lượt, và chỉ trả **dữ liệu phân loại** — không lời thoại, không quyền ghi, không gọi Clinic.

Ranh giới (§8.3.2): prompt chỉ nhận transcript, mã câu hỏi, hướng gọi, hành động đang chờ và các nhãn
rule của CHÍNH lượt này. Không hồ sơ bệnh nhân, không `verify.*`, không object appointment / slot,
không câu bot đọc lịch, không lịch sử cuộc gọi.

Mọi giá trị model được nhận đều mang `Provenance.FALLBACK` và span nguyên văn có trong transcript;
span được đối chiếu trên bản CÒN dấu câu để lời phủ định / đính chính không bị nhập mệnh đề.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from callbot.engine.extraction.model_budget import report_model_status
from callbot.engine.extraction.schema import (
    Agreement,
    ClinicalLevel,
    Intent,
    QuestionId,
    compact_json_schema,
)
from callbot.engine.extraction.text import normalize
from callbot.engine.types import CancelReason, Direction, PendingAction
from callbot.tracing.generation import finish_generation, generation_scope, normalized_result
from inference.common.telemetry import InferenceTimer
from inference.llm.gateway import LLMGateway
from inference.llm.prompt.semantic import PROMPT_VERSION, PROMPT_VERSIONS, build_messages

logger = logging.getLogger(__name__)

# Model viết span nối hai đoạn rời sẽ tạo bằng chứng không có thật; từ chối thẳng.
_FORGED_SPAN_MARKERS = (" + ", "...", "…")


class ReplyKind(str, Enum):
    """Câu người gọi làm gì với câu hỏi đang chờ. Nội bộ IE; không lưu vào session."""

    CONFIRM_ACTION = "CONFIRM_ACTION"  # đồng ý chính hành động đang chờ
    DECLINE_ACTION = "DECLINE_ACTION"  # từ chối chính hành động đang chờ
    INFORM_REASON = "INFORM_REASON"  # chỉ nêu lý do, chưa quyết
    CHANGE_INTENT = "CHANGE_INTENT"  # chuyển sang nhu cầu khác
    QUESTION = "QUESTION"  # hỏi lại / hỏi thêm
    AMBIGUOUS = "AMBIGUOUS"  # không đủ căn cứ


_DECISIVE_KINDS = frozenset({ReplyKind.CONFIRM_ACTION, ReplyKind.DECLINE_ACTION})


@dataclass(frozen=True)
class RuleCandidates:
    """Nhãn rule của lượt hiện tại — gợi ý CÓ THỂ SAI, không phải đáp án bắt buộc."""

    intent: Optional[Intent] = None
    intent_span: Optional[str] = None
    agreement: Optional[Agreement] = None
    agreement_span: Optional[str] = None
    cancel_reason: Optional[CancelReason] = None
    reason_span: Optional[str] = None


@dataclass(frozen=True)
class SemanticContext:
    """Đúng những gì được phép vào prompt. Không dựng từ `CallContext`, không serialize cả object."""

    transcript: str
    question_id: Optional[QuestionId]
    direction: Direction
    allowed_intents: tuple[Intent, ...]
    route_reason: str
    pending_action: Optional[PendingAction] = None
    # Câu hỏi có thực sự ở lượt ngay trước không (tính từ question_turn). Chỉ để giải thích câu đáp;
    # guardrail vẫn kiểm riêng trước mọi lệnh ghi.
    answers_last_question: bool = True
    candidates: RuleCandidates = RuleCandidates()


@dataclass(frozen=True)
class SemanticOutcome:
    """Kết quả đã validate và đã neo span vào transcript."""

    reply_kind: ReplyKind
    reply_span: Optional[str] = None
    intent: Optional[Intent] = None
    intent_span: Optional[str] = None
    cancel_reason: Optional[CancelReason] = None
    reason_span: Optional[str] = None
    clinical: Optional[ClinicalLevel] = None
    clinical_span: Optional[str] = None


class SemanticExtractor(Protocol):
    """Interface riêng của tầng ngữ nghĩa — KHÔNG dùng lại `FallbackExtractor` của slot filling tên,
    để không nhồi ngữ cảnh phiên vào prompt trích tên."""

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]: ...


# --- Kết quả có cấu trúc ----------------------------------------------------------------

_INTENT_VALUES = Literal["CONFIRM", "CANCEL", "RESCHEDULE", "BOOK", "OUT_OF_SCOPE"]
_REPLY_VALUES = Literal[
    "CONFIRM_ACTION", "DECLINE_ACTION", "INFORM_REASON", "CHANGE_INTENT", "QUESTION", "AMBIGUOUS"
]
_REASON_VALUES = Literal[
    "PATIENT_UNAVAILABLE", "NO_LONGER_NEEDED", "WENT_ELSEWHERE", "COST", "UNSPECIFIED"
]
_CLINICAL_VALUES = Literal["EMERGENCY", "ADVICE_REQUEST", "MENTION"]


class SemanticReading(BaseModel):
    """Schema đóng gửi cho Structured Outputs: mọi khóa bắt buộc, không có khóa lạ.

    Không có `outcome`, `appointment_id`, `slot_id`, câu thoại hay trường "được phép ghi" —
    model không có đường nào để tự khai quyền ghi.
    """

    model_config = ConfigDict(json_schema_extra=compact_json_schema, strict=True, extra="forbid")

    intent: _INTENT_VALUES | None
    intent_span: str | None
    reply_kind: _REPLY_VALUES
    reply_span: str | None
    cancel_reason: _REASON_VALUES | None
    reason_span: str | None
    clinical: _CLINICAL_VALUES | None
    clinical_span: str | None


def ground_reading(reading: SemanticReading, context: SemanticContext) -> Optional[SemanticOutcome]:
    """Bỏ mọi kết luận không có căn cứ trong chính transcript của lượt này.

    Trả `None` nghĩa là không dùng được gì — bộ gọi đi nhánh thận trọng. Có span thật KHÔNG đồng
    nghĩa nhãn đúng; bảng quyền ở `semantic_router.merge_semantic` mới quyết được dùng tới đâu.
    """
    kind = ReplyKind(reading.reply_kind)
    reply_span = _grounded(reading.reply_span, context.transcript)
    for label, span in (
        (reading.intent, reading.intent_span),
        (reading.cancel_reason, reading.reason_span),
        (reading.clinical, reading.clinical_span),
    ):
        if (label is None) != (span is None) or (
            span is not None and _grounded(span, context.transcript) is None
        ):
            return None
    if reading.reply_span is not None and reply_span is None:
        return None
    if kind in _DECISIVE_KINDS and reply_span is None:
        # Kết luận chắc chắn mà không chỉ được chỗ nào trong câu -> không nhận
        return None

    intent, intent_span = _read_intent(reading, context)
    if reading.intent is not None and intent is None:
        return None
    reason, reason_span = _read_reason(reading, context)
    clinical = ClinicalLevel(reading.clinical) if reading.clinical is not None else None
    clinical_span = _grounded(reading.clinical_span, context.transcript)
    if (clinical is None) != (reading.clinical_span is None) or (
        clinical is not None and clinical_span is None
    ):
        return None

    if kind is ReplyKind.INFORM_REASON and reason is None:
        return None
    if kind is ReplyKind.CHANGE_INTENT and intent is None:
        return None
    return SemanticOutcome(
        kind, reply_span, intent, intent_span, reason, reason_span, clinical, clinical_span
    )


def _read_intent(
    reading: SemanticReading, context: SemanticContext
) -> tuple[Optional[Intent], Optional[str]]:
    if reading.intent is None:
        return None, None
    intent = Intent(reading.intent)
    span = _grounded(reading.intent_span, context.transcript)
    if intent not in context.allowed_intents or span is None:
        return None, None
    return intent, span


def _read_reason(
    reading: SemanticReading, context: SemanticContext
) -> tuple[Optional[CancelReason], Optional[str]]:
    """`null` = chưa nêu lý do (giữ lý do cũ). `UNSPECIFIED` + span = có nói nhưng không chọn được."""
    if reading.cancel_reason is None:
        return None, None
    span = _grounded(reading.reason_span, context.transcript)
    if span is None:
        return None, None
    return reading.cancel_reason, span


def _grounded(span: Optional[str], transcript: str) -> Optional[str]:
    """Span phải là một đoạn LIỀN MẠCH của transcript, đối chiếu trên bản còn dấu câu (§8.3.3)."""
    if not span:
        return None
    if any(marker in span for marker in _FORGED_SPAN_MARKERS):
        return None
    candidate = normalize(span)
    return candidate if candidate and candidate in normalize(transcript) else None


# --- Adapter gọi model ------------------------------------------------------------------


class LLMSemanticExtractor:
    """Một request cho cả lượt; mọi lỗi provider trả `None` để bộ gọi đi nhánh hỏi lại."""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        max_input_chars: int,
        max_completion_tokens: int,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if prompt_version not in PROMPT_VERSIONS:
            raise ValueError(f"prompt version không hỗ trợ: {prompt_version}")
        self._gateway = gateway
        self._max_input_chars = max_input_chars
        self._max_completion_tokens = max_completion_tokens
        self._prompt_version = prompt_version
        # Trạng thái lượt gần nhất: bộ chuyển provider đọc để phân biệt lỗi dịch vụ với model đã trả lời
        self.last_status: Optional[str] = None

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        timer = InferenceTimer()
        status = "invalid_response"
        reply = None
        try:
            if not normalize(context.transcript):
                status = "empty"
                return None
            if len(context.transcript) > self._max_input_chars:
                # Cắt bớt có thể cắt mất chính lời phủ định -> để nhánh hỏi lại xử lý
                status = "too_long"
                return None
            messages = build_messages(context, version=self._prompt_version)
            schema = SemanticReading.model_json_schema()
            status = "error"
            with generation_scope("llm.semantic_extract") as generation:
                try:
                    reply = self._gateway.generate_structured(
                        messages,
                        schema=schema,
                        schema_name=self._prompt_version,
                        max_completion_tokens=self._max_completion_tokens,
                    )
                    if reply.status != "completed" or reply.content is None:
                        status = reply.status
                        return None
                    status = "invalid_response"
                    reading = SemanticReading.model_validate_json(reply.content)
                    outcome = ground_reading(reading, context)
                    status = "accepted" if outcome is not None else "rejected"
                    return outcome
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
            # Không log transcript, prompt, tên, hay khóa API — chỉ số liệu kỹ thuật.
            logger.info(
                "Semantic fallback: %s",
                status,
                extra={
                    "semantic_provider": self._gateway.provider_name,
                    "semantic_model": self._gateway.model,
                    "semantic_prompt_version": self._prompt_version,
                    "semantic_route_reason": context.route_reason,
                    "semantic_question_id": (
                        context.question_id.value if context.question_id else None
                    ),
                    "semantic_status": status,
                    "semantic_elapsed_ms": timer.elapsed_ms,
                    "semantic_prompt_tokens": reply.prompt_tokens if reply else None,
                    "semantic_completion_tokens": reply.completion_tokens if reply else None,
                },
            )
        return None
