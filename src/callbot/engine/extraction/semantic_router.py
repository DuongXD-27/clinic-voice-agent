"""Quyết định KHI NÀO gọi tầng ngữ nghĩa và hợp nhất kết quả — hàm thuần, có test riêng.

Hai việc tách bạch:
- `route_semantic`: trả `None` (không gọi) hoặc một mã lý do gọi. Không dùng điểm tin cậy tự khai
  của rule hay model; `found == True` KHÔNG có nghĩa là rule đã đúng.
- `merge_semantic`: bảng quyền T-05 §8.3.4. Model được làm rõ lý do và chuyển nhu cầu; model KHÔNG được
  nâng NONE / UNCLEAR / REFUSE thành AGREE để mở khóa lệnh ghi.
"""

from enum import Enum
from typing import Optional

from callbot.engine.extraction.schema import (
    Agreement,
    ClinicalLevel,
    ExtractionResult,
    Field,
    Intent,
    Provenance,
    QuestionId,
    TurnContext,
)
from callbot.engine.extraction.semantic import (
    ReplyKind,
    RuleCandidates,
    SemanticContext,
    SemanticOutcome,
)
from callbot.engine.extraction.text import clean, strip_diacritics
from callbot.engine.types import CancelReason, Direction


class RouteReason(str, Enum):
    """Vì sao lượt này cần đọc lại bằng ngữ nghĩa."""

    CANCEL_REFUSAL_WITH_REASON = "CANCEL_REFUSAL_WITH_REASON"  # từ chối + lý do trong cùng câu
    CANCEL_CONTRADICTION = "CANCEL_CONTRADICTION"  # tín hiệu ngược nhau / ngập ngừng
    CANCEL_UNRESOLVED = "CANCEL_UNRESOLVED"  # câu hủy không thuộc tập toàn câu rõ ràng
    INTENT_UNCLEAR = "INTENT_UNCLEAR"  # ASK_INTENT / CONFIRM_READBACK chưa có ý định dùng được


# Câu rõ ràng khi khớp TOÀN CÂU — rule đã đủ, không làm chậm đường rõ bằng một request model.
# Khớp toàn câu, không phải "có chứa": "hủy giúp tôi nhưng mà..." không nằm trong tập này.
_SETTLED_UTTERANCES = (
    # đồng ý hủy
    "hủy đi",
    "hủy lịch",
    "hủy giúp tôi",
    "hủy giúp em",
    "hủy lịch giúp tôi",
    "hủy lịch khám",
    "đúng hủy",
    "đúng hủy đi",
    # từ chối hủy
    "không hủy",
    "không hủy nữa",
    "đừng hủy",
    "thôi không hủy nữa",
    "giữ lịch",
    "giữ nguyên lịch",
    "vẫn giữ lịch",
    # đáp lễ / khẳng định trần — rule cho UNCLEAR, model không được đoán hộ
    "vâng",
    "dạ",
    "ừ",
    "có",
    "được",
    "đúng",
    "ok",
    "đồng ý",
)
_SETTLED = frozenset(clean(u) for u in _SETTLED_UTTERANCES) | frozenset(
    strip_diacritics(clean(u)) for u in _SETTLED_UTTERANCES
)

# Ý định model được phép đề xuất, theo ngữ cảnh. KHÔNG lọc lại bằng `allowed_in_direction`: inbound
# phải giữ CANCEL / RESCHEDULE / CONFIRM để Dialogue còn chuyển OUT_OF_SCOPE (§8.3.3).
_OUTBOUND_BUSINESS = (Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE)
_INBOUND_BUSINESS = (Intent.BOOK, Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE)

_SEMANTIC_QUESTIONS = frozenset(
    {QuestionId.CANCEL_RECONFIRM, QuestionId.ASK_INTENT, QuestionId.CONFIRM_READBACK}
)
_TRANSFER_CLINICAL = frozenset({ClinicalLevel.EMERGENCY, ClinicalLevel.ADVICE_REQUEST})
# Câu trả lời có/không dứt khoát: Dialogue đã có đường đi, không cần đọc lại bằng ngữ nghĩa.
_DECISIVE_AGREEMENTS = frozenset({Agreement.AGREE, Agreement.REFUSE})
# Policy đã đủ căn cứ kết thúc lượt: model không được trì hoãn hay xóa quyết định này.
_POLICY_INTENTS = frozenset(
    {Intent.REQUEST_HUMAN, Intent.NOT_PATIENT, Intent.OUT_OF_SCOPE, Intent.REPEAT_REQUEST}
)


def route_semantic(
    *,
    question_id: Optional[QuestionId],
    transcript: str,
    intent: Field[Intent],
    clinical: Field[ClinicalLevel],
    agreement: Field[Agreement],
    cancel_reason: Field[CancelReason],
) -> Optional[RouteReason]:
    """`None` = chỉ dùng rule. Gọi sau khi rule của mọi trường liên quan đã chạy."""
    text = clean(transcript)
    if not text or question_id not in _SEMANTIC_QUESTIONS:
        return None
    if clinical.value in _TRANSFER_CLINICAL or intent.value in _POLICY_INTENTS:
        return None
    if text in _SETTLED:
        return None

    if question_id is QuestionId.CANCEL_RECONFIRM:
        if agreement.value is Agreement.REFUSE and cancel_reason.found:
            return RouteReason.CANCEL_REFUSAL_WITH_REASON
        if agreement.value is Agreement.UNCLEAR and agreement.found:
            return RouteReason.CANCEL_CONTRADICTION
        if agreement.value is Agreement.AGREE:
            # Rule đã đủ ngưỡng SF-05 nhưng câu không thuộc tập toàn câu rõ: kiểm lại mệnh đề
            return RouteReason.CANCEL_UNRESOLVED
        return RouteReason.CANCEL_UNRESOLVED
    # ASK_INTENT / CONFIRM_READBACK: chỉ gọi khi lượt này KHÔNG cho Dialogue đường đi nào — không có
    # ý định dùng được VÀ cũng không có câu trả lời có/không dứt khoát. Một lượt đã nói rõ nhu cầu
    # ("tôi muốn hủy lịch") đi thẳng nhánh nghiệp vụ, không tốn thêm một request.
    if intent.value in (Intent.NONE, None) and agreement.value not in _DECISIVE_AGREEMENTS:
        return RouteReason.INTENT_UNCLEAR
    return None


def build_semantic_context(
    ctx: TurnContext, result: ExtractionResult, route_reason: RouteReason
) -> SemanticContext:
    """Chỉ các trường được phép (§8.3.2). Không có tên / ngày sinh, hồ sơ, slot hay câu bot đọc lịch."""
    return SemanticContext(
        transcript=result.transcript,
        question_id=result.question_id,
        direction=ctx.direction,
        allowed_intents=_allowed_intents(ctx.direction),
        route_reason=route_reason.value,
        pending_action=ctx.pending_action,
        answers_last_question=ctx.question_turn is not None and ctx.question_turn == ctx.turn - 1,
        candidates=RuleCandidates(
            intent=result.intent.value if result.intent.found else None,
            intent_span=result.intent.span,
            agreement=result.agreement.value if result.agreement.found else None,
            agreement_span=result.agreement.span,
            cancel_reason=result.cancel_reason.value if result.cancel_reason.found else None,
            reason_span=result.cancel_reason.span,
        ),
    )


def _allowed_intents(direction: Direction) -> tuple[Intent, ...]:
    return _INBOUND_BUSINESS if direction == "inbound" else _OUTBOUND_BUSINESS


def merge_semantic(
    result: ExtractionResult,
    outcome: Optional[SemanticOutcome],
    route_reason: RouteReason,
    allowed_intents: tuple[Intent, ...],
) -> ExtractionResult:
    """Bảng quyền §8.3.4. Mọi giá trị nhận từ model mang `Provenance.FALLBACK` và span thật."""
    if outcome is None:
        return _without_model(result, route_reason)

    intent, agreement, reason = result.intent, result.agreement, result.cancel_reason
    kind = outcome.reply_kind

    if outcome.cancel_reason is not None and kind is not ReplyKind.DECLINE_ACTION:
        # Lý do có căn cứ được cập nhật ở mọi kiểu trả lời trừ khi người gọi đang bỏ hủy hẳn
        reason = Field(outcome.cancel_reason, Provenance.FALLBACK, span=outcome.reason_span)

    if kind is ReplyKind.INFORM_REASON:
        # Chỉ nêu lý do: KHÔNG phải đồng ý, cũng không phải từ chối. `Field.nothing` để Dialogue đi
        # nhánh "đã ghi nhận lý do" và hỏi lại (§8.3.4).
        agreement = Field.nothing(Agreement.UNCLEAR)
    elif kind is ReplyKind.DECLINE_ACTION:
        agreement = Field(Agreement.REFUSE, Provenance.FALLBACK, span=outcome.reply_span)
    elif kind is ReplyKind.CHANGE_INTENT and outcome.intent in allowed_intents:
        intent = Field(outcome.intent, Provenance.FALLBACK, span=outcome.intent_span)
        if result.question_id is QuestionId.CANCEL_RECONFIRM and outcome.intent is Intent.CONFIRM:
            # "không hủy nữa, tôi vẫn đi khám": đổi sang giữ lịch chính là từ chối hủy. Dialogue
            # không có nhánh CONFIRM ở câu hủy, để `nothing` sẽ thành "em chưa hiểu".
            agreement = Field(Agreement.REFUSE, Provenance.FALLBACK, span=outcome.intent_span)
        else:
            agreement = Field.nothing(Agreement.UNCLEAR)
    elif kind in (ReplyKind.QUESTION, ReplyKind.AMBIGUOUS):
        agreement = Field(
            Agreement.UNCLEAR, Provenance.FALLBACK, span=outcome.reply_span or result.transcript
        )
    elif kind is ReplyKind.CONFIRM_ACTION:
        # Model KHÔNG nâng ngưỡng ghi: giữ nguyên kết luận rule. Câu đã bị router đánh dấu mâu thuẫn
        # thì vẫn phải hỏi lại và nhận xác nhận mới ở lượt sau.
        agreement = _no_promotion(result.agreement, route_reason)

    return _replace(result, intent=intent, agreement=agreement, cancel_reason=reason)


def _no_promotion(agreement: Field[Agreement], route_reason: RouteReason) -> Field[Agreement]:
    if route_reason in (RouteReason.CANCEL_CONTRADICTION, RouteReason.CANCEL_REFUSAL_WITH_REASON):
        return Field(Agreement.UNCLEAR, Provenance.FALLBACK, span=agreement.span)
    return agreement


def _without_model(result: ExtractionResult, route_reason: RouteReason) -> ExtractionResult:
    """Model tắt, timeout hoặc kết quả không dùng được: giữ rule rõ ràng, hạ trường đang nghi ngờ.

    Lời từ chối hủy tường minh ("không hủy nữa, dù tôi không đủ tiền") vẫn là từ chối — đó là rule
    rõ, không phải trường đang nghi ngờ. Ngược lại, AGREE trong một câu mâu thuẫn thì hạ UNCLEAR.
    """
    if (
        route_reason is RouteReason.CANCEL_CONTRADICTION
        and result.agreement.value is Agreement.AGREE
    ):
        return _replace(
            result,
            agreement=Field(
                Agreement.UNCLEAR, result.agreement.provenance, span=result.agreement.span
            ),
        )
    return result


def _replace(result: ExtractionResult, **changes) -> ExtractionResult:
    fields = {
        name: getattr(result, name)
        for name in (
            "turn",
            "question_id",
            "transcript",
            "full_name",
            "dob",
            "intent",
            "clinical",
            "agreement",
            "slot_choice",
            "cancel_reason",
            "line_signal",
            "silent",
        )
    }
    return ExtractionResult(**{**fields, **changes})
