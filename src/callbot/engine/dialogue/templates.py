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
# Lượt 0 khi tra cứu hồ sơ không cho dữ liệu để xác minh (T-02): vẫn công bố AI, không hỏi tên,
# không nói lý do ("số này chưa có hồ sơ" cũng là thông tin về hồ sơ). Lượt 1 chuyển máy.
GREETING_HANDOFF_OUTBOUND = (
    f"Dạ em xin chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Em xin phép chuyển máy tới nhân viên để hỗ trợ anh chị ạ."
)
GREETING_HANDOFF_INBOUND = (
    f"Dạ Vinmec xin nghe, em là {AI_DISCLOSURE} của tổng đài. "
    "Em xin phép chuyển máy tới nhân viên để hỗ trợ anh chị ạ."
)
# Người nghe máy chỉ nói "alo" sau câu chào: chào lại, nhắc lại AI [R-26] và hỏi tên
GREETING_BACK_OUTBOUND = (
    f"Dạ em chào anh chị ạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Cho em hỏi em đang nói chuyện với anh chị nào ạ?"
)
GREETING_BACK_INBOUND = (
    f"Dạ em chào anh chị ạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Anh chị vui lòng cho em biết họ tên đầy đủ ạ?"
)
ASK_NAME_AGAIN = "Dạ, anh chị vui lòng cho em xin họ và tên đầy đủ ạ."
# Đã có ngày sinh, còn thiếu tên. §1.1.2: không nhắc lại ngày sinh người gọi vừa nói.
ASK_NAME_AFTER_DOB = "Dạ, anh chị cho em xin thêm họ và tên đầy đủ ạ."
# Người gọi nói nhu cầu trước khi đọc tên: ghi nhận nhưng phải xác minh trước (SF-03)
ASK_NAME_FOR_REQUEST = (
    "Dạ vâng, để hỗ trợ anh chị, em cần xác minh thông tin trước. "
    "Anh chị cho em xin họ và tên đầy đủ ạ."
)
ASK_DOB_FOR_REQUEST = (
    "Dạ vâng, để hỗ trợ anh chị, em cần xác minh thông tin trước. "
    "Anh chị cho em xin ngày tháng năm sinh ạ."
)
ASK_NAME_DECLINED = (
    "Dạ, em cần họ và tên để xác minh đúng người trước khi hỗ trợ. "
    "Anh chị vui lòng cho em xin họ và tên đầy đủ ạ."
)
ASK_DOB = "Dạ, anh chị cho em xin ngày tháng năm sinh ạ."
ASK_DOB_AGAIN = "Dạ, em chưa nghe rõ. Anh chị nhắc lại giúp em ngày, tháng, năm sinh ạ."
# dob INVALID (31/02, thiếu năm, năm 2 chữ số mơ hồ, tuổi, âm lịch): không nhắc lại điều người gọi vừa nói
ASK_DOB_INVALID = "Dạ, anh chị vui lòng cho em xin đủ ngày, tháng, năm sinh theo dương lịch ạ."
ASK_DOB_DECLINED = (
    "Dạ, em cần ngày tháng năm sinh để xác minh đúng người trước khi hỗ trợ. "
    "Anh chị vui lòng cho em xin ạ."
)
# Câu hỏi MỞ (ASK_INTENT): "vâng" không phải câu trả lời hợp lệ, không suy ra đặt lịch
ASK_INTENT_INBOUND = "Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ?"
ASK_CHANGE_OR_CANCEL = "Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?"
ASK_ATTENDANCE = "Anh chị có đến khám được theo lịch này không ạ?"
NOT_UNDERSTOOD = "Dạ, em chưa hiểu ý anh chị. Anh chị nói lại giúp em được không ạ?"
SILENCE = "Alo, anh chị còn nghe máy không ạ?"
CANCEL_RECONFIRM = "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
# Câu lựa chọn A/B khi agreement UNCLEAR (thiết kế §5.6): từ đáp lễ không còn là câu trả lời hợp lệ.
# Nói luôn cụm cần nói, vì ngưỡng AGREE ở đây đòi động từ hủy tường minh (SF-05).
CANCEL_CHOICE = (
    "Dạ, anh chị muốn hủy hay giữ lịch khám ạ? Nếu muốn hủy, anh chị xác nhận “hủy lịch” giúp em ạ."
)
# Đã hiểu lý do nhưng người gọi chưa xác nhận hủy (T-05 §3.3). Chỉ đọc tiền tố ghi nhận khi lý do
# đã xác định — không đọc lại lý do phỏng đoán, và ghi nhận lý do KHÔNG phải đã đồng ý hủy.
CANCEL_REASON_NOTED = (
    "Dạ, em đã ghi nhận lý do. Anh chị xác nhận hủy lịch khám này chứ ạ? "
    "Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ."
)
BOOKING_ABANDONED = "Dạ, em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ?"
SLOT_TAKEN = "Dạ, khung giờ đó vừa có người đặt. "
SLOT_NO_MATCH = "Dạ, em chưa thấy khung giờ đó. "
SLOT_AMBIGUOUS = "Dạ, có nhiều khung giờ phù hợp. "
TRANSFER = "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ."
# §1.1.7: không để lại chi tiết lịch hẹn trên hộp thư thoại
GOODBYE_UNREACHABLE = "Dạ, em xin phép gọi lại sau ạ. Chào anh chị."

_PERIOD_WORDS = ((12, "sáng"), (18, "chiều"), (24, "tối"))
# §1.1.3: đọc lại "date, time and clinic". Mock chỉ trả `clinic_id` (Listing 3, không có /clinics):
# tên lấy theo seed Mock (clinic-mock `store.CLINICS`). Id lạ -> "Vinmec", không đoán tên cơ sở.
CLINIC_NAMES = {
    "cl_vinmec": "Vinmec Times City",
    "c_001": "Phòng khám Đa khoa Trung tâm",
    "c_002": "Phòng khám Đa khoa Cầu Giấy",
}


def greeting(direction: str) -> str:
    """Câu chào mở đầu dùng chung cho mọi transport.

    [R-26] công bố là trợ lý ảo AI ngay câu đầu + [R-02] hỏi tên bằng câu hỏi mở.
    """
    return GREETING_OUTBOUND if direction == "outbound" else GREETING_INBOUND


def greeting_back(direction: str) -> str:
    """Trả lời "alo" ngay sau câu chào mở đầu."""
    return GREETING_BACK_OUTBOUND if direction == "outbound" else GREETING_BACK_INBOUND


def greeting_handoff(direction: str) -> str:
    """Câu chào khi không thể xác minh (không có hồ sơ / không đọc được hồ sơ): [R-26], không hỏi tên."""
    return GREETING_HANDOFF_OUTBOUND if direction == "outbound" else GREETING_HANDOFF_INBOUND


def speak_datetime(iso: str) -> str:
    moment = to_local(datetime.fromisoformat(iso))
    period = next(word for limit, word in _PERIOD_WORDS if moment.hour < limit)
    hour = moment.hour if moment.hour <= 12 else moment.hour - 12
    minute = f" {moment.minute}" if moment.minute else ""
    return f"{hour} giờ{minute} {period} ngày {moment.day} tháng {moment.month}"


def attendance_facts(appointment: dict[str, Any]) -> str:
    """Ngày, giờ, cơ sở (§1.1.3) — dùng chung cho mọi câu đọc lại và câu báo đã xác nhận."""
    return f"{speak_datetime(appointment['starts_at'])} tại {clinic_name(appointment)}"


def appointment_summary(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """Figure 0 rev 1.1: tóm tắt + đọc lại ngày, giờ, cơ sở + hỏi đến được không, trong một lượt."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Cảm ơn anh chị. Lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)} ạ. {ASK_ATTENDANCE}"
    )


def attendance_readback(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """§1.1.3: đọc lại ngày, giờ, cơ sở trước khi CONFIRMED."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em xin xác nhận lại: lịch khám {_department(appointment)}"
        f"{attendance_facts(appointment)}. Anh chị đồng ý chứ ạ?"
    )


def attendance_reread(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """Câu trả lời chưa rõ: đọc lại (kiến trúc §3.2 "Chưa rõ -> O_READ") bằng câu hỏi có / không —
    "vâng" là câu trả lời hợp lệ, khác câu A/B."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    )


def confirmed(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """Báo đã xác nhận bằng chính bản ghi Mock trả về sau lệnh ghi, không bằng câu đã đọc."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em đã xác nhận lịch khám {attendance_facts(appointment)} cho anh chị. "
        "Hẹn gặp anh chị ạ."
    )


def keep_appointment(ctx: CallContext, appointment: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Dạ, em giữ nguyên lịch khám {attendance_facts(appointment)} cho anh chị. {ASK_ATTENDANCE}"
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
    if outcome == "CANCELLED":
        return "Dạ, em đã hủy lịch khám cho anh chị ạ."
    if outcome in ("RESCHEDULED", "BOOKED") and slot:
        return f"Dạ, em đã đặt lịch {speak_datetime(slot['starts_at'])} cho anh chị ạ."
    return "Dạ, em cảm ơn anh chị ạ."


def clinic_name(appointment: dict[str, Any]) -> str:
    return (
        appointment.get("clinic_name")
        or CLINIC_NAMES.get(appointment.get("clinic_id") or "")
        or "Vinmec"
    )


def _department(appointment: dict[str, Any]) -> str:
    department = appointment.get("department")
    return f"{department} " if department else ""
