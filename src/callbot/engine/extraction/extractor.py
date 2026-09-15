"""Information Extraction — điều phối các bộ trích xuất theo câu bot vừa hỏi (thiết kế v1.1).

Trách nhiệm: trích + chuẩn hoá các trường ở §1, gắn `provenance`.
Không được: đọc hồ sơ bệnh nhân; ra quyết định nghiệp vụ; chọn `transfer_reason` (Policy làm).

Thứ tự trong một lượt:
1. line_signal  — outbound, cho tới khi xác minh xong; khác NONE thì dừng, không đọc câu hộp thư thoại thành tên.
2. clinical     — mọi lượt, trước intent.
3. intent       — ở bước danh tính chỉ chạy nhãn an toàn (xem IDENTITY_SAFE_INTENTS).
4. full_name    — chỉ ASK_NAME.
5. dob          — chỉ ASK_DOB.
   OUT_OF_SCOPE ở bước danh tính — chỉ khi câu trả lời không phải tên / ngày sinh.
6. agreement    — chỉ câu hỏi xác nhận.
7. slot_choice  — chỉ OFFER_SLOTS.
8. cancel_reason — khi đang hủy.
"""

from typing import Optional

from callbot.engine.extraction.agreement import extract_agreement
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.dob import extract_dob
from callbot.engine.extraction.fallback import FallbackExtractor, guard_fallback
from callbot.engine.extraction.full_name import extract_full_name
from callbot.engine.extraction.intent import PRIORITY, allowed_in_direction, extract_intent
from callbot.engine.extraction.line_signal import extract_line_signal
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
from callbot.engine.extraction.slot_choice import extract_slot_choice
from callbot.engine.extraction.text import clean

# Ở bước hỏi tên / ngày sinh không chạy intent nghiệp vụ: "Lê Văn Thôi", "Trần Văn Được" không được
# thành REFUSE / CONFIRM. Chỉ giữ nhãn cần cho an toàn hoặc để không đọc nhầm câu thành tên:
# - REQUEST_HUMAN: người gọi xin gặp người thật trước khi xác minh.
# - NOT_PATIENT:   "tôi là vợ anh ấy" không phải tên; outbound phải chuyển máy, không tiết lộ.
# - REPEAT_REQUEST: "gì cơ" không phải tên, và không tính vào §1.1.5.
IDENTITY_SAFE_INTENTS = frozenset({Intent.REQUEST_HUMAN, Intent.NOT_PATIENT, Intent.REPEAT_REQUEST})
# OUT_OF_SCOPE ở bước danh tính chỉ xét SAU khi không trích được tên / ngày sinh: hợp đồng §1.1.5 và
# §1.2.3 bắt chuyển máy OUT_OF_SCOPE (không phải NOT_UNDERSTOOD sau 2 lần hỏi lại), nhưng "thanh toan"
# trùng tên "Thanh Toàn" khi mất dấu — tên hợp lệ thì luôn thắng.
_IDENTITY_FALLBACK_INTENTS = frozenset({Intent.OUT_OF_SCOPE})

_TRANSFER_CLINICAL = frozenset({ClinicalLevel.EMERGENCY, ClinicalLevel.ADVICE_REQUEST})

# Intent không mâu thuẫn với câu hỏi xác nhận. Intent khác (vd. RESCHEDULE khi đang xác nhận hủy)
# hạ AGREE xuống UNCLEAR: người gọi đang nói việc khác, không phải đồng ý hành động đang chờ.
_CONSISTENT_INTENTS: dict[QuestionId, frozenset[Intent]] = {
    QuestionId.ASK_ATTENDANCE: frozenset({Intent.NONE, Intent.CONFIRM}),
    QuestionId.CONFIRM_READBACK: frozenset({Intent.NONE, Intent.CONFIRM}),
    QuestionId.SLOT_READBACK: frozenset({Intent.NONE, Intent.RESCHEDULE, Intent.BOOK, Intent.CONFIRM}),
    QuestionId.CANCEL_RECONFIRM: frozenset({Intent.NONE, Intent.CANCEL}),
}
_CANCEL_QUESTIONS = frozenset({QuestionId.CANCEL_RECONFIRM, QuestionId.ASK_CANCEL_REASON})


class InformationExtractor:
    def __init__(self, fallback: Optional[FallbackExtractor] = None, name_fallback: bool = False) -> None:
        self._fallback = fallback
        # NER cho tên chỉ bật từ tuần 3 (thiết kế §8); intent/agreement dùng tuyến sau khi có `fallback`.
        self._name_fallback = name_fallback

    def extract(self, ctx: TurnContext, transcript: str, *, silence_ms: int = 0) -> ExtractionResult:
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
                return ExtractionResult.only(ctx.turn, question, transcript, line_signal=line_signal)

        clinical = extract_clinical(transcript)
        intent = self._intent(ctx, transcript)

        full_name: Field[str] = skipped
        if question is QuestionId.ASK_NAME and intent.value is Intent.NONE and clinical.value not in _TRANSFER_CLINICAL:
            full_name = self._full_name(transcript)

        dob = extract_dob(transcript, ctx.today) if question is QuestionId.ASK_DOB else skipped

        if question in IDENTITY_QUESTIONS and intent.value is Intent.NONE and not full_name.found and dob.value is None:
            out_of_scope = extract_intent(transcript, ctx.direction, _IDENTITY_FALLBACK_INTENTS)
            if out_of_scope.found:
                intent = out_of_scope

        agreement: Field[Agreement] = skipped
        if question in CONFIRMATION_QUESTIONS:
            agreement = self._agreement(question, transcript, intent, clinical)

        slot_choice = skipped
        if question is QuestionId.OFFER_SLOTS:
            slot_choice = extract_slot_choice(transcript, ctx.slots, ctx.presented_slot_ids, ctx.now)

        cancel_reason = skipped
        if question in _CANCEL_QUESTIONS or intent.value is Intent.CANCEL:
            cancel_reason = extract_cancel_reason(transcript)

        return ExtractionResult(
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
        )

    # --- Từng trường có tuyến sau ------------------------------------------------

    def _intent(self, ctx: TurnContext, transcript: str) -> Field[Intent]:
        identity_step = ctx.question_id in IDENTITY_QUESTIONS
        allowed = IDENTITY_SAFE_INTENTS if identity_step else frozenset(PRIORITY)
        result = extract_intent(transcript, ctx.direction, allowed)
        if result.found or identity_step or self._fallback is None:
            return result
        allowed_here = frozenset(i for i in allowed if allowed_in_direction(i, ctx.direction))
        guarded = guard_fallback(self._fallback.intent(transcript, allowed_here), transcript, Intent.NONE)
        if guarded.found and guarded.value not in allowed_here:
            return Field.nothing(Intent.NONE)
        return guarded

    def _full_name(self, transcript: str) -> Field[str]:
        result = extract_full_name(transcript)
        if result.found or not self._name_fallback or self._fallback is None:
            return result
        guarded = guard_fallback(self._fallback.full_name(transcript), transcript, None)
        # Tên do NER trả về cũng phải nằm nguyên văn trong transcript, không chỉ span
        if guarded.found and f" {clean(guarded.value or '')} " not in f" {clean(transcript)} ":
            return Field.nothing()
        return guarded

    def _agreement(
        self, question: QuestionId, transcript: str, intent: Field[Intent], clinical: Field[ClinicalLevel]
    ) -> Field[Agreement]:
        result = extract_agreement(transcript, question)
        if not result.found and self._fallback is not None:
            # Tuyến sau chỉ xét câu nói vòng không có tín hiệu nào ("hôm đó tôi bận mất rồi").
            result = guard_fallback(self._fallback.agreement(transcript, question), transcript, Agreement.UNCLEAR)
            if question is QuestionId.CANCEL_RECONFIRM and result.value is Agreement.AGREE:
                # SF-05: hủy lịch cần động từ hủy tường minh — luật đã không thấy thì mô hình không được mở khóa
                result = Field(Agreement.UNCLEAR, Provenance.FALLBACK, span=result.span)

        contradicted = intent.value not in _CONSISTENT_INTENTS[question] or clinical.value in _TRANSFER_CLINICAL
        if result.value is Agreement.AGREE and contradicted:
            return Field(Agreement.UNCLEAR, result.provenance, span=result.span)
        return result

