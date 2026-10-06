"""Information Extraction — điều phối các bộ trích xuất theo câu bot vừa hỏi (thiết kế v1.1).

Trách nhiệm: trích + chuẩn hoá các trường ở §1, gắn `provenance`.
Không được: đọc hồ sơ bệnh nhân; ra quyết định nghiệp vụ; chọn `transfer_reason` (Policy làm).

Thứ tự trong một lượt:
1. line_signal  — outbound, cho tới khi xác minh xong; khác NONE thì dừng, không đọc câu hộp thư thoại thành tên.
2. clinical     — mọi lượt, trước intent.
3. intent       — ở bước danh tính chỉ chạy nhãn an toàn (xem IDENTITY_SAFE_INTENTS).
4. dob          — ASK_DOB; và ASK_NAME, vì người gọi hay nói gộp "Nguyễn Văn A, sinh 14/3/1978" (T-02).
5. full_name    — chỉ ASK_NAME; câu có ngày sinh thì chỉ trích trên phần đứng trước ngày sinh.
   Nhãn dự phòng ở bước danh tính (OUT_OF_SCOPE, ý định nghiệp vụ, CANNOT_PROVIDE) — chỉ khi câu
   trả lời không phải tên / ngày sinh.
6. slot_choice  — câu hỏi chọn slot: OFFER_SLOTS, SLOT_READBACK, SLOT_REFUSE_CHOICE, ASK_SLOT_PREFERENCE.
7. agreement    — câu hỏi xác nhận; ở các câu hỏi chọn slot khác chỉ khi không rút ra tiêu chí slot
   (chỉ ra REFUSE/UNCLEAR).
8. cancel_reason — khi đang hủy; và ở CONFIRM_READBACK / ASK_INTENT outbound, nơi lý do "đã khám
   chỗ khác rồi" tự nó là yêu cầu hủy (`implied_cancel`, xét ở bước 3 trước tuyến model).
"""

import logging
from dataclasses import replace
from typing import Optional

from callbot.engine.extraction.agreement import (
    confirmation_veto,
    conflicting_confirmation,
    extract_agreement,
)
from callbot.engine.extraction.cancel_promotion import promotion_rejection
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.dob import read_dob
from callbot.engine.extraction.fallback import (
    FallbackExtractor,
    SlotFillingResult,
    SlotFillingStatus,
    guard_fallback,
)
from callbot.engine.extraction.full_name import (
    MIN_WORDS_AFTER_HONORIFIC,
    name_after_dob,
    name_before_dob,
    read_full_name,
    valid_name_span,
)
from callbot.engine.extraction.honorific import strip_honorific
from callbot.engine.extraction.identity import Reading, Reason, identity_value
from callbot.engine.extraction.implied_cancel import implied_cancel
from callbot.engine.extraction.intent import PRIORITY, allowed_in_direction, extract_intent
from callbot.engine.extraction.line_signal import extract_line_signal
from callbot.engine.extraction.model_budget import (
    invoke_model,
    model_turn,
    model_used,
    report_model_status,
)
from callbot.engine.extraction.schema import (
    CONFIRMATION_QUESTIONS,
    IDENTITY_QUESTIONS,
    Agreement,
    ClinicalLevel,
    ExtractionResult,
    Field,
    Intent,
    LineSignal,
    Provenance,
    QuestionId,
    TurnContext,
)
from callbot.engine.extraction.semantic import ReplyKind, SemanticExtractor, SemanticOutcome
from callbot.engine.extraction.semantic_router import (
    RouteReason,
    build_semantic_context,
    merge_semantic,
    route_semantic,
)
from callbot.engine.extraction.slot_choice import extract_slot_choice
from callbot.engine.extraction.text import clean
from callbot.engine.types import CancelReason
from callbot.tracing import trace_event

# Ở bước hỏi tên / ngày sinh không chạy intent nghiệp vụ: "Lê Văn Thôi", "Trần Văn Được" không được
# thành REFUSE / CONFIRM. Chỉ giữ nhãn cần cho an toàn hoặc để không đọc nhầm câu thành tên:
# - REQUEST_HUMAN: người gọi xin gặp người thật trước khi xác minh.
# - NOT_PATIENT:   "tôi là vợ anh ấy" không phải tên; outbound phải chuyển máy, không tiết lộ.
# - REPEAT_REQUEST: "gì cơ" không phải tên, và không tính vào §1.1.5.
IDENTITY_SAFE_INTENTS = frozenset({Intent.REQUEST_HUMAN, Intent.NOT_PATIENT, Intent.REPEAT_REQUEST})
# Nhãn ở bước danh tính chỉ xét SAU khi không trích được tên / ngày sinh — tên hợp lệ luôn thắng
# ("thanh toan" trùng tên "Thanh Toàn" khi mất dấu; "Lê Văn Thôi", "Trần Văn Được"):
# - OUT_OF_SCOPE: §1.1.5, §1.2.3 bắt chuyển máy OUT_OF_SCOPE, không phải NOT_UNDERSTOOD sau 2 lần hỏi lại.
# - Ý định nghiệp vụ: người gọi nói nhu cầu trước khi đọc tên ("tôi muốn đặt lịch", Hình 0 contract) —
#   Dialogue hỏi lại tên, không tính là không hiểu; ý định không được dùng trước khi xác minh xong.
# - CANNOT_PROVIDE: "tôi không nhớ ngày sinh" — xác minh không thực hiện được (§1.1.1).
_IDENTITY_FALLBACK_INTENTS = frozenset(
    {
        Intent.OUT_OF_SCOPE,
        Intent.RESCHEDULE,
        Intent.CANCEL,
        Intent.BOOK,
        Intent.CONFIRM,
        Intent.CANNOT_PROVIDE,
    }
)

logger = logging.getLogger(__name__)

_TRANSFER_CLINICAL = frozenset({ClinicalLevel.EMERGENCY, ClinicalLevel.ADVICE_REQUEST})

# Intent không mâu thuẫn với câu hỏi xác nhận. Intent khác (vd. RESCHEDULE khi đang xác nhận hủy)
# hạ AGREE xuống UNCLEAR: người gọi đang nói việc khác, không phải đồng ý hành động đang chờ.
_CONSISTENT_INTENTS: dict[QuestionId, frozenset[Intent]] = {
    QuestionId.ASK_ATTENDANCE: frozenset({Intent.NONE, Intent.CONFIRM}),
    QuestionId.CONFIRM_READBACK: frozenset({Intent.NONE, Intent.CONFIRM}),
    QuestionId.SLOT_READBACK: frozenset(
        {Intent.NONE, Intent.RESCHEDULE, Intent.BOOK, Intent.CONFIRM}
    ),
    QuestionId.CANCEL_RECONFIRM: frozenset({Intent.NONE, Intent.CANCEL}),
}
_CANCEL_QUESTIONS = frozenset({QuestionId.CANCEL_RECONFIRM, QuestionId.ASK_CANCEL_REASON})
# Outbound: câu đọc lịch và câu "đổi hay hủy". Lý do ở đây được ghi nhận, và lý do "đã khám chỗ khác
# rồi" là yêu cầu hủy (`implied_cancel`). Không gồm câu xác nhận hủy: ở đó lý do có luồng riêng (T-05).
_REASON_AS_REQUEST_QUESTIONS = frozenset({QuestionId.CONFIRM_READBACK, QuestionId.ASK_INTENT})
# Câu hỏi mà người gọi có thể trả lời bằng khung / tiêu chí thời gian / "khung khác" (T-10)
_SLOT_QUESTIONS = frozenset(
    {
        QuestionId.OFFER_SLOTS,
        QuestionId.SLOT_READBACK,
        QuestionId.SLOT_REFUSE_CHOICE,
        QuestionId.ASK_SLOT_PREFERENCE,
    }
)


def _resolve_refusal_inside_reason(
    question: Optional[QuestionId],
    agreement: Field[Agreement],
    cancel_reason: Field[CancelReason],
) -> Field[Agreement]:
    """ "tôi không đủ tiền" ở câu xác nhận hủy: chữ "không" thuộc về LÝ DO, không phải lời từ chối.

    Luật agreement chỉ nhìn từ khóa nên trả REFUSE và Dialogue sẽ bỏ hủy, mất luôn lý do. Khi đoạn
    làm nên REFUSE nằm gọn trong đoạn làm nên reason, lượt này là lượt chỉ nêu lý do: trả về "không
    có tín hiệu đồng ý" để Dialogue ghi nhận lý do rồi hỏi lại (T-05 §8.3.1, §8.3.4).

    Lời từ chối tường minh vẫn thắng: "không hủy nữa, dù tôi không đủ tiền" có đoạn REFUSE là
    "không hủy nữa", không nằm trong "không đủ tiền" — giữ nguyên REFUSE.
    """
    if question is not QuestionId.CANCEL_RECONFIRM or agreement.value is not Agreement.REFUSE:
        return agreement
    if not cancel_reason.found or not agreement.span or not cancel_reason.span:
        return agreement
    if not _within(cancel_reason.span, agreement.span):
        return agreement
    return Field.nothing(Agreement.UNCLEAR)


# Sau merge, AGREE nâng từ model chỉ giữ được khi lượt vẫn là câu trả lời thuần cho câu hỏi hủy
_PROMOTION_INTENTS = frozenset({Intent.NONE, Intent.CANCEL})


def _keep_cancel_threshold(
    rule: Field[Agreement],
    result: ExtractionResult,
    ctx: TurnContext,
    outcome: Optional[SemanticOutcome],
    *,
    promotion_enabled: bool,
) -> ExtractionResult:
    """SF-05: ở câu xác nhận hủy, AGREE chỉ đến từ luật toàn câu (`agreement._cancel_leaves_content`),
    hoặc — khi bật `CANCEL_SEMANTIC_CONFIRM_ENABLED` — từ đề xuất của model ĐÃ KIỂM CHỨNG.

    Chốt này giữ bất biến ở một chỗ cho mọi nhánh hợp nhất (model lỗi, timeout, CONFIRM_ACTION sai),
    kể cả khi bảng quyền `merge_semantic` đổi sau này. Không tin nhãn route hay kết quả merge: mọi
    điều kiện nâng được tính lại từ transcript, outcome và `TurnContext` (evidence T-05, đợt 3).
    """
    if (
        result.question_id is not QuestionId.CANCEL_RECONFIRM
        or result.agreement.value is not Agreement.AGREE
        or rule.value is Agreement.AGREE
    ):
        return result
    rejection = _promotion_rejection(result, ctx, outcome) if promotion_enabled else "disabled"
    if promotion_enabled:
        # Không log transcript hay span — chỉ mã điều kiện
        logger.info(
            "Cancel promotion: %s",
            "accepted" if rejection is None else f"rejected_{rejection}",
            extra={"cancel_promotion": rejection or "accepted"},
        )
    if rejection is None:
        return result
    return replace(
        result,
        agreement=Field(Agreement.UNCLEAR, Provenance.FALLBACK, span=result.agreement.span),
    )


def _promotion_rejection(
    result: ExtractionResult, ctx: TurnContext, outcome: Optional[SemanticOutcome]
) -> Optional[str]:
    """Năm điều kiện của plan §3: `None` khi được nâng, ngược lại là mã điều kiện không đạt."""
    if outcome is None or outcome.reply_kind is not ReplyKind.CONFIRM_ACTION:
        return "outcome"
    if not outcome.reply_span or result.agreement.span != outcome.reply_span:
        return "outcome"
    if ctx.question_id is not QuestionId.CANCEL_RECONFIRM or ctx.question_turn != ctx.turn - 1:
        return "stale"
    if (
        result.intent.value not in _PROMOTION_INTENTS
        or result.clinical.value is not ClinicalLevel.NONE
    ):
        return "context"
    return promotion_rejection(result.transcript, outcome.reply_span)


def _within(outer: str, inner: str) -> bool:
    return f" {inner} " in f" {outer} "


class InformationExtractor:
    def __init__(
        self,
        fallback: Optional[FallbackExtractor] = None,
        name_fallback: bool = False,
        semantic: Optional[SemanticExtractor] = None,
        cancel_semantic_confirm: bool = False,
    ) -> None:
        self._fallback = fallback
        # Factory bật slot filling họ tên theo NAME_FALLBACK_PROVIDER; mặc định chỉ dùng luật.
        self._name_fallback = name_fallback
        # Factory bật tầng ngữ nghĩa theo SEMANTIC_FALLBACK_ENABLED; mặc định bật, thiếu OPENAI_API_KEY thì None.
        self._semantic = semantic
        # CANCEL_SEMANTIC_CONFIRM_ENABLED (mặc định tắt): cho model đề xuất xác nhận hủy có kiểm chứng
        self._cancel_semantic_confirm = cancel_semantic_confirm

    def extract(
        self, ctx: TurnContext, transcript: str, *, silence_ms: int = 0
    ) -> ExtractionResult:
        with model_turn() as budget:
            result = self._extract(ctx, transcript, silence_ms=silence_ms)
            if budget.used:
                trace_event(
                    "ie.model",
                    model=budget.model,
                    latency_ms=budget.latency_ms,
                    model_result=budget.status,
                )
            if budget.status in {"TIMEOUT", "ERROR", "INVALID"}:
                result = replace(
                    result,
                    intent=Field.nothing(Intent.NONE),
                    agreement=Field.nothing(Agreement.UNCLEAR),
                )
            conflict = ctx.question_id in CONFIRMATION_QUESTIONS and conflicting_confirmation(
                transcript, ctx.question_id
            )
            if conflict or (
                result.agreement.value is Agreement.AGREE and confirmation_veto(transcript)
            ):
                result = replace(
                    result, agreement=Field(Agreement.UNCLEAR, Provenance.EXACT, transcript)
                )
            return replace(result, model_status=budget.status, confirmation_conflict=conflict)

    def _extract(
        self, ctx: TurnContext, transcript: str, *, silence_ms: int = 0
    ) -> ExtractionResult:
        """`silence_ms` lấy nguyên từ lượt harness (Listing 2).

        Im lặng xác định bằng `silence_ms > 0` (Phụ lục A), không bằng transcript rỗng: người gọi có nói
        mà ASR không ra chữ (`silence_ms == 0`, transcript rỗng) là KHÔNG HIỂU, không phải im lặng.
        """
        skipped = Field.skipped()
        question = ctx.question_id
        if silence_ms > 0:
            return ExtractionResult.only(ctx.turn, question, transcript, silent=True)

        line_signal: Field[LineSignal] = skipped
        # Rev 1.1 §4.2.5: VOICEMAIL đến bằng clip lời chào, không nói ở lượt nào -> xét suốt các bước trước xác minh
        if ctx.direction == "outbound" and (question is None or question in IDENTITY_QUESTIONS):
            line_signal = extract_line_signal(transcript)
            if line_signal.value is not LineSignal.NONE:
                return ExtractionResult.only(
                    ctx.turn, question, transcript, line_signal=line_signal
                )

        clinical = extract_clinical(transcript)
        reason_as_request = ctx.direction == "outbound" and question in _REASON_AS_REQUEST_QUESTIONS
        early_reason = extract_cancel_reason(transcript) if reason_as_request else None
        intent = self._intent(ctx, transcript, clinical, early_reason)

        dob_reading = read_dob(transcript, ctx.today) if question in IDENTITY_QUESTIONS else None
        dob = dob_reading.field if dob_reading is not None else skipped

        full_name: Field[str] = skipped
        name_reading = Reading(Field.nothing(), Reason.NO_SIGNAL)
        if (
            question is QuestionId.ASK_NAME
            and intent.value is Intent.NONE
            and clinical.value not in _TRANSFER_CLINICAL
        ):
            if dob_reading is not None and dob_reading.zone:
                # Câu gộp: tên chỉ nằm ngoài vùng ngày, và chỉ được lấy khi ranh giới chắc chắn.
                # Vùng ngày cũng được nhận khi ngày không hợp lệ ("Nguyễn Văn A, sinh ngày
                # 31/02/1978" -> giữ tên, hỏi lại ngày), nhưng câu chỉ tình cờ có chữ số
                # ("bảo hiểm có chi trả 80% không") thì không có vùng nào để cắt.
                zone = name_before_dob(transcript) or name_after_dob(transcript)
                name_reading = self._full_name(zone, transcript, ctx) if zone else name_reading
            else:
                name_reading = self._full_name(transcript, transcript, ctx)
            full_name = name_reading.field

        if (
            question in IDENTITY_QUESTIONS
            and intent.value is Intent.NONE
            and not full_name.found
            # Không có vùng ngày nào được nhận ra: "bảo hiểm có chi trả 80% không" có chữ số nên
            # dob ra INVALID, nhưng đó vẫn là câu ngoài phạm vi. Ngược lại, người gọi đã đọc một
            # ngày (dù không dùng được) thì họ có cung cấp được — không phải CANNOT_PROVIDE.
            and (dob_reading is None or not dob_reading.zone)
        ):
            fallback_intent = extract_intent(
                transcript, ctx.direction, _IDENTITY_FALLBACK_INTENTS, business_step=False
            )
            if fallback_intent.found:
                intent = fallback_intent

        slot_choice = skipped
        if question in _SLOT_QUESTIONS:
            slot_choice = extract_slot_choice(
                transcript, ctx.slots, ctx.presented_slot_ids, ctx.now
            )

        agreement: Field[Agreement] = skipped
        if question in CONFIRMATION_QUESTIONS:
            agreement = self._agreement(question, transcript, intent, clinical)
        elif question in _SLOT_QUESTIONS and not slot_choice.found:
            # Chỉ để nhận lời từ chối chọn slot ("thôi không đổi nữa"). Các câu hỏi này không có ngưỡng
            # AGREE trong agreement._agree_span nên kết quả không bao giờ là AGREE, không mở khóa ghi.
            agreement = extract_agreement(transcript, question)

        cancel_reason = skipped
        if early_reason is not None:
            cancel_reason = early_reason
        elif question in _CANCEL_QUESTIONS or intent.value is Intent.CANCEL:
            cancel_reason = extract_cancel_reason(transcript)

        # Rule của mọi trường liên quan đã chạy xong: giờ mới thấy được xung đột giữa chúng.
        agreement = _resolve_refusal_inside_reason(question, agreement, cancel_reason)
        route_reason = route_semantic(
            question_id=question,
            transcript=transcript,
            intent=intent,
            clinical=clinical,
            agreement=agreement,
            cancel_reason=cancel_reason,
            direction=ctx.direction,
            cancel_promotion=self._cancel_semantic_confirm and self._semantic is not None,
        )
        result = ExtractionResult(
            turn=ctx.turn,
            question_id=question,
            transcript=transcript,
            full_name=full_name,
            dob=dob,
            intent=intent,
            clinical=clinical,
            agreement=agreement,
            slot_choice=slot_choice,
            cancel_reason=cancel_reason,
            line_signal=line_signal,
            name_identity=identity_value(name_reading, transcript, confidence=ctx.asr_confidence),
            dob_identity=(
                identity_value(dob_reading, transcript, confidence=ctx.asr_confidence)
                if dob_reading is not None
                else None
            ),
        )
        if route_reason is None:
            return result
        if self._semantic is None or model_used():
            if route_reason is RouteReason.CLINICAL_UNRESOLVED:
                return merge_semantic(result, None, route_reason, ())
            return result
        merged, outcome = self._apply_semantic(ctx, result, route_reason)
        return _keep_cancel_threshold(
            agreement, merged, ctx, outcome, promotion_enabled=self._cancel_semantic_confirm
        )

    def _apply_semantic(
        self, ctx: TurnContext, result: ExtractionResult, route_reason: RouteReason
    ) -> tuple[ExtractionResult, Optional[SemanticOutcome]]:
        """Một lần gọi model cho cả lượt; kết quả hợp nhất theo bảng quyền ở `semantic.merge`.

        Trả kèm outcome để chốt SF-05 tự kiểm chứng, không tin kết quả merge."""
        assert self._semantic is not None
        context = build_semantic_context(ctx, result, route_reason)
        try:
            outcome = invoke_model(self._semantic, lambda: self._semantic.analyze(context))
        except Exception:  # noqa: BLE001 — lỗi tuyến sau không được thành lỗi lượt gọi
            logger.warning("Tầng ngữ nghĩa lỗi, dùng kết quả thận trọng", exc_info=False)
            outcome = None
        return merge_semantic(result, outcome, route_reason, context.allowed_intents), outcome

    # --- Từng trường có tuyến sau ------------------------------------------------

    def _intent(
        self,
        ctx: TurnContext,
        transcript: str,
        clinical: Field[ClinicalLevel],
        reason: Optional[Field[CancelReason]],
    ) -> Field[Intent]:
        identity_step = ctx.question_id in IDENTITY_QUESTIONS
        allowed = IDENTITY_SAFE_INTENTS if identity_step else frozenset(PRIORITY)
        result = extract_intent(transcript, ctx.direction, allowed)
        if result.found or identity_step:
            return result
        if reason is not None and clinical.value is ClinicalLevel.NONE:
            # Chỉ khi luật không ra nhãn nào: CONFIRM / RESCHEDULE / ngoài phạm vi vẫn thắng
            span = implied_cancel(transcript, reason)
            if span is not None:
                return Field(Intent.CANCEL, reason.provenance, span=span)
        if self._fallback is None or self._name_fallback:
            return result
        allowed_here = frozenset(i for i in allowed if allowed_in_direction(i, ctx.direction))
        guarded = guard_fallback(
            invoke_model(self._fallback, lambda: self._fallback.intent(transcript, allowed_here)),
            transcript,
            Intent.NONE,
        )
        if guarded.found and guarded.value not in allowed_here:
            report_model_status("invalid_response")
            return Field.nothing(Intent.NONE)
        return guarded

    def _full_name(self, zone: str, transcript: str, ctx: TurnContext) -> Reading[str]:
        """Preserve rule evidence and never restore a name after a failed model operation."""
        reading = read_full_name(zone)
        if reading.field.found or reading.reason not in (
            Reason.NO_SIGNAL,
            Reason.UNRESOLVED_BOUNDARY,
            Reason.UNANCHORED,
        ):
            return reading
        if not self._name_fallback or self._fallback is None:
            if reading.reason is Reason.UNANCHORED:
                return read_full_name(zone, require_anchor=False)
            return reading
        result = self._slot_fill(reading.reason, zone, transcript, ctx)
        if result.status is SlotFillingStatus.ACCEPTED:
            return Reading(result.field, Reason.OK, zone)
        if result.status is SlotFillingStatus.NO_NAME:
            return Reading(Field.nothing(), Reason.NO_SIGNAL, zone)
        report_model_status("invalid_response")
        return Reading(Field.nothing(), Reason.UNCERTAIN, zone)

    def _slot_fill(
        self, reason: Reason, zone: str, transcript: str, ctx: TurnContext
    ) -> SlotFillingResult:
        unavailable = SlotFillingResult(SlotFillingStatus.UNAVAILABLE, Field.nothing())
        logger.info("Name fallback route: %s", reason.value)
        try:
            proposed = invoke_model(
                self._fallback,
                lambda: self._fallback.full_name(
                    transcript,
                    question_id=QuestionId.ASK_NAME,
                    bot_question=ctx.question_text,
                ),
            )
        except Exception:
            logger.warning("Name fallback failed; requesting the name again", exc_info=False)
            return unavailable
        if proposed is None:
            return unavailable
        if not isinstance(proposed, SlotFillingResult):
            report_model_status("invalid_response")
            return unavailable
        if proposed.status is not SlotFillingStatus.ACCEPTED:
            return SlotFillingResult(proposed.status, Field.nothing(), proposed.elapsed_ms)
        rejected = SlotFillingResult(
            SlotFillingStatus.REJECTED, Field.nothing(), proposed.elapsed_ms
        )
        guarded = guard_fallback(proposed.field, transcript, None)
        if not guarded.found or not guarded.value or not _contains(zone, clean(guarded.value)):
            return rejected
        name = strip_honorific(clean(guarded.value), MIN_WORDS_AFTER_HONORIFIC)
        if not valid_name_span(name):
            return rejected
        return SlotFillingResult(
            SlotFillingStatus.ACCEPTED,
            Field(name, guarded.provenance, span=guarded.span),
            proposed.elapsed_ms,
        )

    def _agreement(
        self,
        question: QuestionId,
        transcript: str,
        intent: Field[Intent],
        clinical: Field[ClinicalLevel],
    ) -> Field[Agreement]:
        # "tôi sẽ đến", "xác nhận" ở câu hỏi đến khám là đồng ý tham dự (T-04); agreement tự bỏ qua ở câu khác
        attendance = intent.span if intent.value is Intent.CONFIRM else None
        result = extract_agreement(transcript, question, attendance=attendance)
        if (
            not result.found
            and self._fallback is not None
            and not self._name_fallback
            and not model_used()
        ):
            # Tuyến sau chỉ xét câu nói vòng không có tín hiệu nào ("hôm đó tôi bận mất rồi").
            result = guard_fallback(
                invoke_model(
                    self._fallback, lambda: self._fallback.agreement(transcript, question)
                ),
                transcript,
                Agreement.UNCLEAR,
            )
            if question is QuestionId.CANCEL_RECONFIRM and result.value is Agreement.AGREE:
                # SF-05: hủy lịch cần động từ hủy tường minh — luật đã không thấy thì mô hình không được mở khóa
                result = Field(Agreement.UNCLEAR, Provenance.FALLBACK, span=result.span)

        contradicted = (
            intent.value not in _CONSISTENT_INTENTS[question]
            or clinical.value in _TRANSFER_CLINICAL
        )
        if result.value is Agreement.AGREE and contradicted:
            return Field(Agreement.UNCLEAR, result.provenance, span=result.span)
        return result


def _contains(text: str, words: str) -> bool:
    return bool(words) and f" {words} " in f" {clean(text)} "
