"""Câu thoại mẫu. Hàm nào nói chi tiết lịch hẹn đều qua assert_can_disclose (SF-03)."""

from datetime import datetime
from typing import Any

from callbot.engine.extraction.schema import to_local
from callbot.engine.policy import guardrails
from callbot.engine.session.context import CallContext

# [R-26] Cụm công bố trợ lý ảo AI. Nguồn duy nhất: mọi câu chào và test nghiệm thu
# đều tham chiếu về đây, đổi chữ ở một chỗ này là đổi toàn hệ thống.
AI_DISCLOSURE = "trợ lý ảo AI"

GREETING_OUTBOUND = (
    f"Dạ em xin chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Cho em hỏi em đang nói chuyện với anh chị nào ạ?"
)
GREETING_INBOUND = (
    f"Dạ Vinmec xin nghe, em là {AI_DISCLOSURE} của tổng đài. "
    "Anh chị vui lòng cho em biết họ tên đầy đủ ạ?"
)
ASK_NAME_AGAIN = "Dạ, anh chị vui lòng cho em xin họ và tên đầy đủ ạ."
ASK_DOB = "Dạ, anh chị cho em xin ngày tháng năm sinh ạ."
ASK_DOB_AGAIN = "Dạ, em chưa nghe rõ. Anh chị nhắc lại giúp em ngày, tháng, năm sinh ạ."
# Câu hỏi MỞ (ASK_INTENT): "vâng" không phải câu trả lời hợp lệ, không suy ra đặt lịch
ASK_INTENT_INBOUND = "Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ?"
ASK_CHANGE_OR_CANCEL = "Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?"
ASK_ATTENDANCE = "Anh chị có đến khám được theo lịch này không ạ?"
NOT_UNDERSTOOD = "Dạ, em chưa hiểu ý anh chị. Anh chị nói lại giúp em được không ạ?"
SILENCE = "Alo, anh chị còn nghe máy không ạ?"
CANCEL_RECONFIRM = "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
# Câu lựa chọn A/B khi agreement UNCLEAR (thiết kế §5.6): từ đáp lễ không còn là câu trả lời hợp lệ
CANCEL_CHOICE = "Dạ, anh chị muốn hủy lịch khám hay giữ lịch ạ?"
ATTENDANCE_CHOICE = "Dạ, anh chị sẽ đến khám theo lịch này, hay muốn đổi hoặc hủy lịch ạ?"
BOOKING_ABANDONED = "Dạ, em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ?"
SLOT_TAKEN = "Dạ, khung giờ đó vừa có người đặt. "
SLOT_NO_MATCH = "Dạ, em chưa thấy khung giờ đó. "
SLOT_AMBIGUOUS = "Dạ, có nhiều khung giờ phù hợp. "
TRANSFER = "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ."
# §1.1.7: không để lại chi tiết lịch hẹn trên hộp thư thoại
GOODBYE_UNREACHABLE = "Dạ, em xin phép gọi lại sau ạ. Chào anh chị."

_PERIOD_WORDS = ((12, "sáng"), (18, "chiều"), (24, "tối"))


def greeting(direction: str) -> str:
    """Câu chào mở đầu dùng chung cho mọi transport.

    [R-26] công bố là trợ lý ảo AI ngay câu đầu + [R-02] hỏi tên bằng câu hỏi mở.
    """
    return GREETING_OUTBOUND if direction == "outbound" else GREETING_INBOUND


def speak_datetime(iso: str) -> str:
    moment = to_local(datetime.fromisoformat(iso))
    period = next(word for limit, word in _PERIOD_WORDS if moment.hour < limit)
    hour = moment.hour if moment.hour <= 12 else moment.hour - 12
    minute = f" {moment.minute}" if moment.minute else ""
    return f"{hour} giờ{minute} {period} ngày {moment.day} tháng {moment.month}"


def appointment_summary(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """Figure 0 rev 1.1: tóm tắt + đọc lại ngày, giờ, cơ sở + hỏi đến được không, trong một lượt."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Cảm ơn anh chị. Lịch khám {appointment.get('department', '')} của anh chị là "
        f"{speak_datetime(appointment['starts_at'])} tại {_clinic(appointment)} ạ. {ASK_ATTENDANCE}"
    )


def attendance_readback(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """§1.1.3: đọc lại ngày, giờ, cơ sở trước khi CONFIRMED."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em xin xác nhận lại: {speak_datetime(appointment['starts_at'])} "
        f"tại {_clinic(appointment)}. Anh chị đồng ý chứ ạ?"
    )


def keep_appointment(ctx: CallContext, appointment: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em giữ nguyên lịch khám {speak_datetime(appointment['starts_at'])} "
        f"tại {_clinic(appointment)} cho anh chị. {ASK_ATTENDANCE}"
    )


def offer_slots(ctx: CallContext, slots: list[dict[str, Any]], prefix: str = "") -> str:
    guardrails.assert_can_disclose(ctx)
    options = "; ".join(
        f"khung {i} là {speak_datetime(s['starts_at'])}" for i, s in enumerate(slots, 1)
    )
    return f"{prefix}Dạ, hiện còn {options}. Anh chị chọn khung nào ạ?"


def slot_readback(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Em chốt khung {speak_datetime(slot['starts_at'])} cho anh chị nhé ạ?"


def slot_choice(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Dạ, anh chị chọn khung {speak_datetime(slot['starts_at'])} hay muốn nghe khung khác ạ?"


def done(outcome: str, slot: dict[str, Any] | None = None) -> str:
    if outcome == "CONFIRMED":
        return "Dạ, em đã xác nhận lịch khám. Hẹn gặp anh chị ạ."
    if outcome == "CANCELLED":
        return "Dạ, em đã hủy lịch khám cho anh chị ạ."
    if outcome in ("RESCHEDULED", "BOOKED") and slot:
        return f"Dạ, em đã đặt lịch {speak_datetime(slot['starts_at'])} cho anh chị ạ."
    return "Dạ, em cảm ơn anh chị ạ."


def _clinic(appointment: dict[str, Any]) -> str:
    return appointment.get("clinic_name") or "Vinmec"
