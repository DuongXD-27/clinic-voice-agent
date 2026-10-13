"""Chặn cứng các severe failure của §3 tại thời điểm thực thi, không tin vào LLM."""

from typing import Optional

from callbot.engine.extraction.agreement import confirmation_veto, without_fallback_lead
from callbot.engine.extraction.schema import Agreement, Intent, Provenance
from callbot.engine.session.context import CallContext, PendingAction
from callbot.engine.session.fsm import confirmation_questions, question_offers_slot


class SevereFailureBlocked(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


def assert_target_appointment(ctx: CallContext, appointment_id: Optional[str]) -> None:
    """SF-01: chỉ ghi vào appointment của cuộc gọi."""
    if appointment_id is None or appointment_id != ctx.target_appointment_id:
        raise SevereFailureBlocked(
            "SF-01", f"Ghi vào {appointment_id}, cuộc gọi thuộc {ctx.target_appointment_id}"
        )


def assert_slot_offered(ctx: CallContext, slot_id: Optional[str]) -> None:
    """SF-02: slot phải do GET /slots trả về trong chính cuộc gọi này."""
    if slot_id is None or ctx.find_slot(slot_id) is None:
        raise SevereFailureBlocked(
            "SF-02", f"Slot {slot_id} không có trong GET /slots của cuộc gọi"
        )


def assert_can_disclose(ctx: CallContext) -> None:
    """SF-03: không tiết lộ chi tiết lịch hẹn trước khi xác minh danh tính."""
    if not ctx.identity_verified:
        raise SevereFailureBlocked("SF-03", "Chưa xác minh danh tính")


_CLINICAL_ADVICE_MARKERS = ("không sao đâu", "nên uống", "liều", "chắc là bệnh", "bình thường thôi")


def assert_no_clinical_advice(utterance: str) -> None:
    """SF-04: lưới an toàn cho câu do LLM sinh. TODO: classifier thay cho từ khoá."""
    lowered = utterance.lower()
    if any(marker in lowered for marker in _CLINICAL_ADVICE_MARKERS):
        raise SevereFailureBlocked("SF-04", "Câu trả lời có dấu hiệu tư vấn lâm sàng")


def assert_action_confirmed(
    ctx: CallContext, action: PendingAction, slot_id: Optional[str] = None
) -> None:
    """Lệnh ghi cần câu trả lời AGREE ở chính lượt này, cho đúng câu hỏi vừa hỏi ở lượt trước,
    đúng hành động và slot.

    SF-05: hủy lịch cần thêm yêu cầu hủy ở một lượt TRƯỚC lượt xác nhận — hai lượt khác nhau.
    """
    question = ctx.question
    expected_questions = confirmation_questions(action)
    confirmations = [
        item
        for item in ctx.evidence_for("CONFIRMATION", action, slot_id)
        if item.label == Agreement.AGREE.value
        and item.turn == ctx.turn
        and item.question_id in expected_questions
        and question is not None
        and item.question_id is question.question_id
        and item.question_turn == question.turn
        # Câu hỏi phải được nói ở lượt NGAY TRƯỚC: "vâng" sau câu nhắc chung (im lặng, "em chưa hiểu")
        # trả lời câu nhắc đó, không phải câu hỏi xác nhận của vài lượt trước (T-08)
        and question.turn == item.turn - 1
        and question.action == action
        and question_offers_slot(ctx, question, slot_id)
        # Đổi / đặt lịch: model không bao giờ mở khóa ghi (plan Jev C2) — chỉ bằng chứng luật được nhận
        and not (action in ("RESCHEDULE", "BOOK") and item.provenance == Provenance.FALLBACK.value)
    ]
    code = "SF-05" if action == "CANCEL" else "CONFIRMATION"
    if ctx.business_write_blocked:
        raise SevereFailureBlocked(code, "Model failed in this turn; business writes are blocked")
    caller = next(
        (
            item.text
            for item in reversed(ctx.history)
            if item.role == "caller" and item.turn == ctx.turn
        ),
        None,
    )

    def vetoed(text: str) -> bool:
        # "Không có thì 3 giờ cũng được": "không" nói về khung vừa thiếu, không phải từ chối khung chọn.
        # Hủy không bao giờ bỏ vế này (SF-05).
        return confirmation_veto(without_fallback_lead(text) if action != "CANCEL" else text)

    if caller is not None and vetoed(caller):
        raise SevereFailureBlocked(code, "Caller confirmation contains a veto")
    if any(vetoed(item.transcript) for item in confirmations):
        raise SevereFailureBlocked(code, "Confirmation evidence contains a veto")
    if not confirmations:
        raise SevereFailureBlocked(code, f"Chưa có xác nhận hợp lệ cho {action} ({slot_id})")
    if action != "CANCEL":
        return
    confirmed_at = min(item.turn for item in confirmations)
    requests = [
        item
        for item in ctx.evidence_for("REQUEST", "CANCEL")
        if item.label == Intent.CANCEL.value and item.turn < confirmed_at
    ]
    if not requests:
        raise SevereFailureBlocked("SF-05", "Chưa có yêu cầu hủy ở lượt trước lượt xác nhận")
