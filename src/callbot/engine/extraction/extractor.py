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
6. slot_choice  — chỉ OFFER_SLOTS.
7. agreement    — câu hỏi xác nhận; ở OFFER_SLOTS chỉ khi không rút ra tiêu chí slot (chỉ ra REFUSE/UNCLEAR).
8. cancel_reason — khi đang hủy.
"""

import logging
from typing import Optional

from callbot.engine.extraction.agreement import extract_agreement
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.dob import read_dob
from callbot.engine.extraction.fallback import FallbackExtractor, guard_fallback
from callbot.engine.extraction.full_name import (
    MIN_WORDS_AFTER_HONORIFIC,
    name_after_dob,
    name_before_dob,
    read_full_name,
)
from callbot.engine.extraction.honorific import strip_honorific
from callbot.engine.extraction.identity import Reason
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
from callbot.engine.extraction.semantic import SemanticExtractor
from callbot.engine.extraction.semantic_router import (
    RouteReason,
    build_semantic_context,
    merge_semantic,
    route_semantic,
)
from callbot.engine.extraction.slot_choice import extract_slot_choice
from callbot.engine.extraction.text import clean
from callbot.engine.types import CancelReason

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


def _within(outer: str, inner: str) -> bool:
    return f" {inner} " in f" {outer} "


class InformationExtractor:
    def __init__(
        self,
        fallback: Optional[FallbackExtractor] = None,
        name_fallback: bool = False,
        semantic: Optional[SemanticExtractor] = None,
    ) -> None:
        self._fallback = fallback
        # Factory bật NER theo NAME_FALLBACK_PROVIDER; mặc định chỉ dùng luật.
        self._name_fallback = name_fallback
        # Factory bật tầng ngữ nghĩa theo SEMANTIC_FALLBACK_ENABLED; mặc định bật, thiếu OPENAI_API_KEY thì None.
        self._semantic = semantic

    def extract(
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
        intent = self._intent(ctx, transcript)

        dob_reading = read_dob(transcript, ctx.today) if question in IDENTITY_QUESTIONS else None
        dob = dob_reading.field if dob_reading is not None else skipped

        full_name: Field[str] = skipped
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
                full_name = self._full_name(zone, transcript) if zone else Field.nothing()
            else:
                full_name = self._full_name(transcript, transcript)

        if (
            question in IDENTITY_QUESTIONS
            and intent.value is Intent.NONE
            and not full_name.found
            # Không có vùng ngày nào được nhận ra: "bảo hiểm có chi trả 80% không" có chữ số nên
            # dob ra INVALID, nhưng đó vẫn là câu ngoài phạm vi. Ngược lại, người gọi đã đọc một
            # ngày (dù không dùng được) thì họ có cung cấp được — không phải CANNOT_PROVIDE.
            and (dob_reading is None or not dob_reading.zone)
        ):
            fallback_intent = extract_intent(transcript, ctx.direction, _IDENTITY_FALLBACK_INTENTS)
            if fallback_intent.found:
                intent = fallback_intent

        slot_choice = skipped
        if question is QuestionId.OFFER_SLOTS:
            slot_choice = extract_slot_choice(
                transcript, ctx.slots, ctx.presented_slot_ids, ctx.now
            )

        agreement: Field[Agreement] = skipped
        if question in CONFIRMATION_QUESTIONS:
            agreement = self._agreement(question, transcript, intent, clinical)
        elif question is QuestionId.OFFER_SLOTS and not slot_choice.found:
            # Chỉ để nhận lời từ chối chọn slot ("thôi không đổi nữa"). OFFER_SLOTS không có ngưỡng
            # AGREE trong agreement._agree_span nên kết quả không bao giờ là AGREE, không mở khóa ghi.
            agreement = extract_agreement(transcript, question)

        cancel_reason = skipped
        if question in _CANCEL_QUESTIONS or intent.value is Intent.CANCEL:
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
        )
        if route_reason is None or self._semantic is None:
            return result
        return self._apply_semantic(ctx, result, route_reason)

    def _apply_semantic(
        self, ctx: TurnContext, result: ExtractionResult, route_reason: RouteReason
    ) -> ExtractionResult:
        """Một lần gọi model cho cả lượt; kết quả hợp nhất theo bảng quyền ở `semantic.merge`."""
        assert self._semantic is not None
        context = build_semantic_context(ctx, result, route_reason)
        try:
            outcome = self._semantic.analyze(context)
        except Exception:  # noqa: BLE001 — lỗi tuyến sau không được thành lỗi lượt gọi
            logger.warning("Tầng ngữ nghĩa lỗi, dùng kết quả thận trọng", exc_info=False)
            outcome = None
        return merge_semantic(result, outcome, route_reason, context.allowed_intents)

    # --- Từng trường có tuyến sau ------------------------------------------------

    def _intent(self, ctx: TurnContext, transcript: str) -> Field[Intent]:
        identity_step = ctx.question_id in IDENTITY_QUESTIONS
        allowed = IDENTITY_SAFE_INTENTS if identity_step else frozenset(PRIORITY)
        result = extract_intent(transcript, ctx.direction, allowed)
        if result.found or identity_step or self._fallback is None:
            return result
        allowed_here = frozenset(i for i in allowed if allowed_in_direction(i, ctx.direction))
        guarded = guard_fallback(
            self._fallback.intent(transcript, allowed_here), transcript, Intent.NONE
        )
        if guarded.found and guarded.value not in allowed_here:
            return Field.nothing(Intent.NONE)
        return guarded

    def _full_name(self, zone: str, transcript: str) -> Field[str]:
        """`zone`: đoạn được phép chứa tên. `transcript`: cả câu, để mô hình còn ngữ cảnh."""
        reading = read_full_name(zone)
        # "Luật chưa hiểu" mới được hỏi mô hình. Câu đã bị luật xác định là phủ định, phân vân,
        # mơ hồ hay câu nghiệp vụ thì mô hình không được lật lại — nếu không, "không phải
        # Nguyễn Văn A" quay về thành "Nguyễn Văn A" và đi thẳng vào Verifier.
        if reading.field.found or reading.reason is not Reason.NO_SIGNAL:
            return reading.field
        if not self._name_fallback or self._fallback is None:
            return Field.nothing()
        guarded = guard_fallback(self._fallback.full_name(transcript), transcript, None)
        # Tên do NER trả về phải nằm nguyên văn trong vùng tên, không chỉ trong transcript:
        # ở câu gộp, mô hình không được lấy chữ từ phần ngày sinh.
        if guarded.found and not _contains(zone, clean(guarded.value or "")):
            return Field.nothing()
        if guarded.found and guarded.value:
            # Danh xưng mô hình chép theo ("ông nguyễn văn a") không thuộc họ tên
            name = strip_honorific(guarded.value, MIN_WORDS_AFTER_HONORIFIC)
            return Field(name, guarded.provenance, span=guarded.span)
        return guarded

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
        if not result.found and self._fallback is not None:
            # Tuyến sau chỉ xét câu nói vòng không có tín hiệu nào ("hôm đó tôi bận mất rồi").
            result = guard_fallback(
                self._fallback.agreement(transcript, question), transcript, Agreement.UNCLEAR
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
