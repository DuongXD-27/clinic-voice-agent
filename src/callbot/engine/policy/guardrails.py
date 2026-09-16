"""Chặn cứng các severe failure của §3 tại thời điểm thực thi, không tin vào LLM."""

from typing import Optional

from callbot.engine.session.context import CallContext


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


def assert_slot_offered(ctx: CallContext, slot_id: str) -> None:
    """SF-02: slot phải do GET /slots trả về trong chính cuộc gọi này."""
    if slot_id not in ctx.offered_slot_ids:
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


def assert_cancel_reconfirmed(ctx: CallContext) -> None:
    """SF-05: hủy lịch cần xác nhận ý định lần thứ hai."""
    if ctx.cancel_confirmations < 2:
        raise SevereFailureBlocked("SF-05", "Chưa có xác nhận hủy lần hai")
