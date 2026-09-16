"""Câu thoại mẫu. Hàm nào nói chi tiết lịch hẹn đều qua assert_can_disclose (SF-03)."""

from datetime import datetime
from typing import Any

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
ASK_INTENT_INBOUND = "Cảm ơn anh chị. Em có thể hỗ trợ anh chị đặt lịch khám ạ?"
ASK_ATTENDANCE = "Anh chị có đến khám được theo lịch này không ạ?"
NOT_UNDERSTOOD = "Dạ, em chưa hiểu ý anh chị. Anh chị nói lại giúp em được không ạ?"
SILENCE = "Alo, anh chị còn nghe máy không ạ?"
CANCEL_RECONFIRM = "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
KEEP_APPOINTMENT = "Dạ, em giữ nguyên lịch khám cho anh chị ạ. Anh chị cần em hỗ trợ gì thêm không ạ?"
NO_SLOTS = "Dạ, hiện chưa có khung giờ phù hợp. Em chuyển máy để nhân viên hỗ trợ anh chị ạ."
TRANSFER = "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ."
GOODBYE_UNREACHABLE = "Dạ, em xin phép gọi lại sau ạ. Chào anh chị."
CLOSED = "Cuộc gọi đã kết thúc."

_PERIOD_WORDS = ((12, "sáng"), (18, "chiều"), (24, "tối"))


def greeting(direction: str) -> str:
    """Câu chào mở đầu dùng chung cho mọi transport.

    [R-26] công bố là trợ lý ảo AI ngay câu đầu + [R-02] hỏi tên bằng câu hỏi mở.
    """
    return GREETING_OUTBOUND if direction == "outbound" else GREETING_INBOUND


def speak_datetime(iso: str) -> str:
    moment = datetime.fromisoformat(iso)
    period = next(word for limit, word in _PERIOD_WORDS if moment.hour < limit)
    hour = moment.hour if moment.hour <= 12 else moment.hour - 12
    minute = f" {moment.minute}" if moment.minute else ""
    return f"{hour} giờ{minute} {period} ngày {moment.day} tháng {moment.month}"


def appointment_summary(ctx: CallContext, appointment: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Cảm ơn anh chị. Lịch khám {appointment.get('department', '')} của anh chị là "
        f"{speak_datetime(appointment['starts_at'])} ạ. {ASK_ATTENDANCE}"
    )


def attendance_readback(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """§1.1.3: đọc lại ngày, giờ, cơ sở trước khi CONFIRMED."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em xin xác nhận lại: {speak_datetime(appointment['starts_at'])} "
        f"tại {appointment.get('clinic_name', 'Vinmec')}. Anh chị đồng ý chứ ạ?"
    )


def offer_slots(ctx: CallContext, slots: list[dict[str, Any]]) -> str:
    guardrails.assert_can_disclose(ctx)
    options = "; ".join(f"khung {i} là {speak_datetime(s['starts_at'])}" for i, s in enumerate(slots, 1))
    return f"Dạ, hiện còn {options}. Anh chị chọn khung nào ạ?"


def slot_readback(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Em chốt khung {speak_datetime(slot['starts_at'])} cho anh chị nhé ạ?"


def done(outcome: str, slot: dict[str, Any] | None = None) -> str:
    if outcome == "CONFIRMED":
        return "Dạ, em đã xác nhận lịch khám. Hẹn gặp anh chị ạ."
    if outcome == "CANCELLED":
        return "Dạ, em đã hủy lịch khám cho anh chị ạ."
    if outcome in ("RESCHEDULED", "BOOKED") and slot:
        return f"Dạ, em đã đặt lịch {speak_datetime(slot['starts_at'])} cho anh chị ạ."
    return "Dạ, em cảm ơn anh chị ạ."
