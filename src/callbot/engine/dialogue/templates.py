"""Câu thoại mẫu. Hàm nào nói chi tiết lịch hẹn đều qua assert_can_disclose (SF-03).

R-01: mọi câu bot nói phải đăng ký ở đây — câu trọn vẹn không chứa dữ liệu lịch qua `static`, câu
dựng từ dữ liệu Clinic qua `@renderer`. Output Guard chặn mọi câu khác (OG-0).

Ràng buộc cho renderer: là hàm THUẦN của (dữ liệu nguồn, tham số). Guard render lại từ dữ liệu gốc
Gateway trả về và so nguyên văn, nên renderer không được đọc thêm gì từ `ctx` (chỉ dùng để assert),
đồng hồ hay trạng thái ngoài. Câu có `success_outcome` chỉ được nói khi lượt có receipt ghi thành công.
"""

from datetime import date, datetime
from typing import Any, Optional

from callbot.engine.dialogue.variants import VARIANT_IDS, choose_variant
from callbot.engine.extraction.schema import to_local
from callbot.engine.policy import guardrails
from callbot.engine.policy.utterances import renderer, static
from callbot.engine.session.context import CallContext

# [R-26] Cụm công bố trợ lý ảo AI. Nguồn duy nhất: mọi câu chào và test nghiệm thu
# đều tham chiếu về đây, đổi chữ ở một chỗ này là đổi toàn hệ thống.
AI_DISCLOSURE = "trợ lý ảo AI"

# Nhóm hỏi đáp có ba nguyên văn; chào đầu, chuyển máy và câu an toàn giữ một nguyên văn.
# Đăng ký từng câu để Output Guard kiểm đúng text, không sửa lời ở lớp TTS.
STATIC_VARIANTS: dict[str, tuple[str, ...]] = {}
_STATIC_GROUPS: dict[str, str] = {}


def _static_group(group: str, *texts: str) -> str:
    if len(texts) != 3 or len(set(texts)) != len(texts):
        raise ValueError(f"{group} cần ba câu khác nhau")
    choices = tuple(
        static(group if index == 0 else f"{group}_{VARIANT_IDS[index]}", text)
        for index, text in enumerate(texts)
    )
    STATIC_VARIANTS[choices[0]] = choices
    _STATIC_GROUPS[choices[0]] = group
    return choices[0]


GREETING_OUTBOUND = static(
    "GREETING_OUTBOUND",
    f"Em chào anh chị. Em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Anh chị cho em xin họ và tên đầy đủ ạ?",
)
GREETING_INBOUND = static(
    "GREETING_INBOUND",
    f"Tổng đài Vinmec xin nghe. Em là {AI_DISCLOSURE}. Anh chị cho em xin họ và tên đầy đủ ạ?",
)
# Không có dữ liệu xác minh: công bố AI, chuyển máy, không tiết lộ lý do tra cứu.
GREETING_HANDOFF_INBOUND = static(
    "GREETING_HANDOFF_INBOUND",
    f"Tổng đài Vinmec xin nghe. Em là {AI_DISCLOSURE}. "
    "Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ.",
)
GREETING_BACK_SHARED = _static_group(
    "GREETING_BACK_SHARED",
    f"Em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em xin họ và tên đầy đủ ạ.",
    f"Anh chị đang nói chuyện với {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Em xin họ và tên đầy đủ để đối chiếu ạ.",
    f"Tổng đài Vinmec đang hỗ trợ anh chị ạ. Em là {AI_DISCLOSURE}. "
    "Anh chị cho em biết họ và tên đầy đủ ạ.",
)
# Hai chiều gọi dùng chung lời giới thiệu lại; giữ tên hằng để call site không đổi nghiệp vụ.
GREETING_BACK_OUTBOUND = GREETING_BACK_INBOUND = GREETING_BACK_SHARED
ASK_NAME_AGAIN = _static_group(
    "ASK_NAME_AGAIN",
    "Anh chị cho em xin lại họ và tên đầy đủ ạ.",
    "Em chưa nghe rõ họ tên. Anh chị đọc lại họ và tên đầy đủ giúp em ạ.",
    "Dạ, anh chị nhắc lại họ và tên đầy đủ để em đối chiếu ạ.",
)
# Đã có ngày sinh: xin thêm tên, không nhắc lại ngày sinh hoặc nói khách đã cung cấp tên.
ASK_NAME_AFTER_DOB = _static_group(
    "ASK_NAME_AFTER_DOB",
    "Anh chị cho em xin thêm họ và tên đầy đủ ạ.",
    "Em xin thêm họ và tên đầy đủ của anh chị để đối chiếu ạ.",
    "Anh chị cho em biết họ và tên đầy đủ để em hoàn tất xác minh ạ.",
)
ASK_NAME_VERIFY_SHARED = _static_group(
    "ASK_NAME_VERIFY_SHARED",
    "Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. "
    "Anh chị cho em xin họ và tên đầy đủ ạ.",
    "Em cần đối chiếu đúng người trước khi trao đổi thông tin lịch khám. "
    "Anh chị cho em biết họ và tên đầy đủ ạ.",
    "Vì bảo mật, em xin họ và tên đầy đủ để xác minh rồi hỗ trợ anh chị ạ.",
)
ASK_NAME_FOR_REQUEST = ASK_NAME_VERIFY_FIRST = ASK_NAME_VERIFY_SHARED
ASK_DOB_VERIFY_SHARED = _static_group(
    "ASK_DOB_VERIFY_SHARED",
    "Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. "
    "Anh chị cho em xin ngày, tháng, năm sinh ạ.",
    "Em cần đối chiếu ngày sinh trước khi trao đổi thông tin lịch khám. "
    "Anh chị đọc đủ ngày, tháng, năm sinh giúp em ạ.",
    "Vì bảo mật, anh chị cho em biết ngày, tháng, năm sinh để em xác minh ạ.",
)
ASK_DOB_FOR_REQUEST = ASK_DOB_VERIFY_FIRST = ASK_DOB_VERIFY_SHARED
# Chưa có call site: giữ một mẫu mỗi tình huống, hoãn thu; không xoá nhánh dự phòng.
ASK_NAME_DECLINED = static(
    "ASK_NAME_DECLINED",
    "Em cần đối chiếu họ tên trước khi hỗ trợ. Anh chị cho em xin họ và tên đầy đủ ạ.",
)
ASK_DOB_INVALID = static(
    "ASK_DOB_INVALID",
    "Anh chị cho em xin đủ ngày, tháng, năm sinh theo dương lịch ạ.",
)
ASK_DOB_DECLINED = static(
    "ASK_DOB_DECLINED",
    "Em cần đối chiếu ngày sinh trước khi hỗ trợ. Anh chị cho em xin đủ ngày, tháng, năm sinh ạ.",
)
ASK_DOB = _static_group(
    "ASK_DOB",
    "Anh chị cho em xin ngày, tháng, năm sinh ạ.",
    "Em xin thêm ngày, tháng, năm sinh để xác minh thông tin ạ.",
    "Dạ, anh chị cho em biết ngày, tháng, năm sinh ạ.",
)
INTRODUCE_AGAIN_ASK_DOB = _static_group(
    "INTRODUCE_AGAIN_ASK_DOB",
    f"Em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em xin ngày, tháng, năm sinh ạ.",
    f"Dạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. Em xin ngày, tháng, năm sinh để đối chiếu ạ.",
    f"Anh chị đang nói chuyện với {AI_DISCLOSURE} của Vinmec. "
    "Anh chị đọc ngày, tháng, năm sinh giúp em ạ.",
)
ASK_DOB_AGAIN = _static_group(
    "ASK_DOB_AGAIN",
    "Em chưa nghe rõ. Anh chị nhắc lại ngày, tháng, năm sinh giúp em ạ.",
    "Anh chị đọc lại đủ ngày, tháng, năm sinh giúp em ạ.",
    "Em xin nghe lại ngày, tháng và năm sinh của anh chị ạ.",
)
ASK_INTENT_INBOUND = _static_group(
    "ASK_INTENT_INBOUND",
    "Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ?",
    "Em đã xác minh xong. Anh chị cần hỗ trợ gì ạ?",
    "Cảm ơn anh chị. Em có thể giúp gì tiếp theo ạ?",
)
ASK_CHANGE_OR_CANCEL = _static_group(
    "ASK_CHANGE_OR_CANCEL",
    "Anh chị muốn đổi lịch hay hủy lịch khám ạ?",
    "Dạ, anh chị cần em hỗ trợ đổi lịch hay hủy lịch khám ạ?",
    "Anh chị muốn chuyển sang giờ khác hay hủy lịch khám này ạ?",
)
# Mảnh câu đi kèm đọc lịch, không thu riêng thay nguyên utterance.
ASK_ATTENDANCE = "Anh chị có đến khám được theo lịch này không ạ?"
NOT_UNDERSTOOD = _static_group(
    "NOT_UNDERSTOOD",
    "Em chưa hiểu rõ ý anh chị. Anh chị nói lại giúp em ạ.",
    "Anh chị nói rõ hơn một chút giúp em được không ạ?",
    "Em chưa nắm được yêu cầu. Anh chị nói lại yêu cầu giúp em ạ.",
)
SILENCE = static("SILENCE", "Alo, anh chị còn nghe máy không ạ?")
HOLD = _static_group(
    "HOLD",
    "Dạ, em chờ anh chị ạ.",
    "Anh chị cứ từ từ, em đang nghe ạ.",
    "Em giữ máy chờ anh chị ạ.",
)
# Hủy luôn cần hai lượt riêng; giữ câu hỏi xác nhận và từ khoá hủy tường minh.
CANCEL_RECONFIRM = static(
    "CANCEL_RECONFIRM", "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
)
CONFIRM_CONFLICT = static(
    "CONFIRM_CONFLICT", "Anh chị có đồng ý xác nhận đến khám theo lịch vừa đọc không ạ?"
)
CANCEL_CONFLICT = static(
    "CANCEL_CONFLICT",
    "Anh chị có chắc chắn muốn hủy lịch khám này không ạ? "
    "Nếu đồng ý, anh chị nói “hủy lịch” giúp em ạ.",
)
SLOT_CONFLICT = static("SLOT_CONFLICT", "Anh chị có đồng ý với khung giờ vừa đọc không ạ?")
CANCEL_CHOICE = static(
    "CANCEL_CHOICE",
    "Anh chị muốn hủy hay giữ lịch khám ạ? Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ.",
)
# Ghi nhận lý do không đồng nghĩa đã nhận được xác nhận hủy.
CANCEL_REASON_NOTED = static(
    "CANCEL_REASON_NOTED",
    "Em đã ghi nhận lý do. Anh chị muốn hủy lịch khám này đúng không ạ? "
    "Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ.",
)
BOOKING_ABANDONED = _static_group(
    "BOOKING_ABANDONED",
    "Em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ?",
    "Dạ, chưa có lịch nào được đặt. Anh chị muốn em hỗ trợ việc gì khác ạ?",
    "Em chưa tạo lịch hẹn. Anh chị có cần hỗ trợ thêm không ạ?",
)
SLOT_TAKEN = "Khung giờ đó vừa có người đặt. "
SLOT_NO_MATCH = "Em chưa thấy khung giờ đó. "
SLOT_AMBIGUOUS = "Có nhiều khung giờ phù hợp. "
# Trang mơ hồ đọc lại y hệt: hỏi khách chọn khung nào, nêu đúng chỗ hai khung khác nhau (review 12-10 §6.1)
SLOT_AMBIGUOUS_AGAIN = "Dạ, "
SLOT_NOT_IN_PAGE = "Em vừa đọc hai khung thôi ạ. "
SLOT_TWO_AT_A_TIME = "Em đọc hai khung để dễ nhớ ạ. "
# Miền prefix riêng: không nhận câu DONE_SAFE hoặc hằng tĩnh bất kỳ làm tiền tố.
SLOT_PREFIXES = frozenset(
    {
        "",
        SLOT_TAKEN,
        SLOT_NO_MATCH,
        SLOT_AMBIGUOUS,
        SLOT_AMBIGUOUS_AGAIN,
        SLOT_NOT_IN_PAGE,
        SLOT_TWO_AT_A_TIME,
    }
)
SLOT_ACTIONS = frozenset({"RESCHEDULE", "BOOK"})
SLOT_INVITES = frozenset({None, *SLOT_ACTIONS})
SLOT_REFUSE_CHOICE: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_REFUSE_CHOICE_RESCHEDULE", "Anh chị muốn nghe giờ khác hay giữ lịch cũ ạ?"
    ),
    "BOOK": static("SLOT_REFUSE_CHOICE_BOOK", "Anh chị muốn nghe giờ khác hay dừng đặt lịch ạ?"),
}
SLOT_EXHAUSTED: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_EXHAUSTED_RESCHEDULE",
        "Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ?",
    ),
    "BOOK": static(
        "SLOT_EXHAUSTED_BOOK",
        "Em đã đọc hết giờ trống phù hợp. Anh chị muốn tìm ngày khác không ạ?",
    ),
}
ROUNDS_EXHAUSTED_TRANSFER = static(
    "ROUNDS_EXHAUSTED_TRANSFER",
    "Lịch cũ của anh chị vẫn giữ nguyên. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ.",
)
NO_SLOTS_TRANSFER = static(
    "NO_SLOTS_TRANSFER", "Hiện chưa có giờ trống. Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ."
)
SLOT_TAKEN_EXHAUSTED: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_TAKEN_EXHAUSTED_RESCHEDULE",
        "Giờ đó vừa có người đặt và không còn giờ phù hợp khác. "
        "Anh chị muốn tìm ngày khác hay giữ lịch cũ ạ?",
    ),
    "BOOK": static(
        "SLOT_TAKEN_EXHAUSTED_BOOK",
        "Giờ đó vừa có người đặt và không còn giờ phù hợp khác. "
        "Anh chị muốn tìm ngày khác không ạ?",
    ),
}
SLOT_TAKEN_ROUNDS_TRANSFER = static(
    "SLOT_TAKEN_ROUNDS_TRANSFER",
    "Giờ đó vừa có người đặt. Lịch cũ vẫn giữ nguyên. "
    "Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ.",
)
SLOT_TAKEN_NO_SLOTS_TRANSFER = static(
    "SLOT_TAKEN_NO_SLOTS_TRANSFER",
    "Giờ đó vừa có người đặt và hiện chưa có giờ trống khác. "
    "Em xin chuyển máy tới nhân viên hỗ trợ anh chị ạ.",
)
DATE_ISSUES = frozenset({"PAST", "INVALID", "TOO_BROAD", "TODAY"})
ASK_SLOT_PREFERENCE: dict[str, str] = {
    "RESCHEDULE": _static_group(
        "ASK_SLOT_PREFERENCE_RESCHEDULE",
        "Anh chị muốn đổi sang ngày nào hoặc buổi nào ạ?",
        "Anh chị cho em biết ngày hoặc buổi muốn đổi lịch sang ạ.",
        "Dạ, anh chị muốn chuyển lịch sang ngày nào hoặc buổi nào ạ?",
    ),
    "BOOK": _static_group(
        "ASK_SLOT_PREFERENCE_BOOK",
        "Anh chị muốn đặt vào ngày nào hoặc buổi nào ạ?",
        "Anh chị cho em biết ngày hoặc buổi muốn đặt lịch ạ.",
        "Dạ, anh chị muốn đặt lịch vào ngày nào hoặc buổi nào ạ?",
    ),
}
TRANSFER = static("TRANSFER", "Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ.")
# Xác minh không đạt: nói lý do chuyển máy nhưng không nói yếu tố nào sai (§1.1.2), dùng chung cho
# không khớp, không có hồ sơ và nhiều hồ sơ cùng khớp (inbound).
IDENTITY_FAILED_TRANSFER = static(
    "IDENTITY_FAILED_TRANSFER",
    "Em chưa xác minh được thông tin của anh chị. "
    "Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ.",
)
# Không để lại chi tiết lịch, không hứa gọi lại khi chưa có scheduler.
GOODBYE_UNREACHABLE = _static_group(
    "GOODBYE_UNREACHABLE",
    "Em xin kết thúc cuộc gọi. Em chào anh chị ạ.",
    "Em xin dừng cuộc gọi tại đây. Chào anh chị ạ.",
    "Cảm ơn anh chị. Em xin kết thúc cuộc gọi ạ.",
)
# Chỉ phát sau receipt thành công; guard vẫn giữ metadata cho từng kết quả.
DONE_SAFE: dict[str, str] = {
    "CONFIRMED": static(
        "CONFIRMED_SAFE",
        "Em đã xác nhận lịch khám cho anh chị. Hẹn gặp anh chị ạ.",
        success_outcome="CONFIRMED",
    ),
    "CANCELLED": static(
        "CANCELLED_SAFE", "Em đã hủy lịch khám cho anh chị ạ.", success_outcome="CANCELLED"
    ),
    "RESCHEDULED": static(
        "RESCHEDULED_SAFE", "Em đã đổi lịch khám cho anh chị ạ.", success_outcome="RESCHEDULED"
    ),
    "BOOKED": static("BOOKED_SAFE", "Em đã đặt lịch khám cho anh chị ạ.", success_outcome="BOOKED"),
    "TRANSFERRED": TRANSFER,
    "UNREACHABLE": GOODBYE_UNREACHABLE,
}


def static_choices(original: str) -> tuple[str, ...]:
    """Nguyên văn hữu hạn của một hành vi; nhóm cố định trả một câu."""
    return STATIC_VARIANTS.get(original, (original,))


def choose_static(ctx: CallContext, original: str) -> str:
    group = _STATIC_GROUPS.get(original)
    if group is None:
        return original
    choices = STATIC_VARIANTS[original]
    variant = choose_variant(ctx, group, variants=VARIANT_IDS[: len(choices)])
    offset = VARIANT_IDS.index(variant)
    used = {item.text for item in ctx.history if item.role == "bot"}
    if ctx.question is not None:
        used.add(ctx.question.text)
    last_bot = next((item.text for item in reversed(ctx.history) if item.role == "bot"), "")
    ordered = [choices[(offset + index) % len(choices)] for index in range(len(choices))]
    fresh = [text for text in ordered if text not in used]
    candidates = fresh or [text for text in ordered if text != last_bot]
    if last_bot.startswith("Dạ"):
        candidates = [text for text in candidates if not text.startswith("Dạ")] or candidates
    return candidates[0]


_PERIOD_WORDS = ((12, "sáng"), (18, "chiều"), (24, "tối"))
_WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")
# §1.1.3 Rev 1.1: đọc ngày, giờ và chuyên khoa. Cơ sở là thông tin bổ sung.
# Mock chỉ trả `clinic_id` (Listing 3, không có /clinics):
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
    """Trả lời "ai đấy?" ở bước hỏi tên: giới thiệu lại AI [R-26] rồi hỏi tên."""
    return GREETING_BACK_OUTBOUND if direction == "outbound" else GREETING_BACK_INBOUND


def speak_datetime(iso: str) -> str:
    """ "3 giờ 30 chiều, thứ Tư ngày 14 tháng 10" — mọi câu xác nhận ngày có thứ (PRD GC-DATE-05)."""
    moment = to_local(datetime.fromisoformat(iso))
    return f"{_speak_time(moment)}, {_speak_date(moment)}"


def _speak_time(moment: datetime) -> str:
    hour = moment.hour if moment.hour <= 12 else moment.hour - 12
    minute = f" {moment.minute}" if moment.minute else ""
    return f"{hour} giờ{minute} {_period(moment)}"


def _speak_date(moment: date) -> str:
    return f"{_WEEKDAYS[moment.weekday()]} ngày {moment.day} tháng {moment.month}"


def _period(moment: datetime) -> str:
    return next(word for limit, word in _PERIOD_WORDS if moment.hour < limit)


def attendance_facts(appointment: dict[str, Any]) -> str:
    """Ngày, giờ, cơ sở (§1.1.3) — dùng chung cho mọi câu đọc lại và câu báo đã xác nhận."""
    return f"{speak_datetime(appointment['starts_at'])}, tại {clinic_name(appointment)}"


@renderer(
    "APPOINTMENT_SUMMARY",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def appointment_summary(
    ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0"
) -> str:
    """Figure 0 rev 1.1: tóm tắt + đọc lại ngày, giờ, cơ sở + hỏi đến được không, trong một lượt."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Cảm ơn anh chị. Lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)} ạ. {ASK_ATTENDANCE}"
    )


@renderer(
    "ATTENDANCE_READBACK",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def attendance_readback(
    ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0"
) -> str:
    """§1.1.3: đọc lại ngày, giờ, chuyên khoa trước khi CONFIRMED."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Em xin xác nhận lại: lịch khám {_department(appointment)}"
        f"{attendance_facts(appointment)}. Anh chị đồng ý chứ ạ?"
    )


@renderer(
    "ATTENDANCE_REREAD",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def attendance_reread(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    """Câu trả lời chưa rõ: đọc lại (kiến trúc §3.2 "Chưa rõ -> O_READ") bằng câu hỏi có / không —
    "vâng" là câu trả lời hợp lệ, khác câu A/B."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    )


@renderer(
    "CANCEL_READBACK",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def cancel_readback(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    """§1.1.4: đọc lại lịch sắp hủy rồi hỏi xác nhận lần hai. Câu hỏi cuối giữ nguyên văn
    CANCEL_RECONFIRM; các câu hỏi lại sau đó (CANCEL_CHOICE...) không đọc lại lịch."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)}. {CANCEL_RECONFIRM}"
    )


@renderer(
    "CONFIRMED_DONE",
    discloses=True,
    success_outcome="CONFIRMED",
    sources={"appointment": "WRITTEN"},
)
def confirmed(ctx: CallContext, appointment: dict[str, Any]) -> str:
    """Báo đã xác nhận bằng chính bản ghi Mock trả về sau lệnh ghi, không bằng câu đã đọc."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"Em đã xác nhận lịch khám {attendance_facts(appointment)} cho anh chị. Hẹn gặp anh chị ạ."
    )


@renderer(
    "KEEP_APPOINTMENT",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def keep_appointment(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Lịch cũ của anh chị vẫn giữ nguyên: lịch khám {_department(appointment)}"
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    )


@renderer(
    "OFFER_SLOTS",
    discloses=True,
    sources={"slots": "SLOTS"},
    str_args={"prefix": SLOT_PREFIXES, "invite": SLOT_INVITES, "variant": VARIANT_IDS},
    slot_scope="PRESENTED",
)
def offer_slots(
    ctx: CallContext,
    slots: list[dict[str, Any]],
    prefix: str = "",
    remaining: int = 0,
    full_date: Optional[date] = None,
    invite: Optional[str] = None,
    *,
    variant: str = "v0",
) -> str:
    """Tối đa 2 khung mỗi lượt (PRD R-25); `remaining` là số khung phù hợp chưa đọc (T-10).

    `full_date`: ngày người gọi xin đã kín (R-29, GC-RES-02) — báo kín rồi đọc các khung gần nhất.
    `invite` (RESCHEDULE / BOOK): người gọi chưa nêu thời gian — đọc khung sớm nhất và mời nêu ngày
    khác trong cùng câu (D-1).
    """
    guardrails.assert_can_disclose(ctx)
    moments = [to_local(datetime.fromisoformat(slot["starts_at"])) for slot in slots]
    more = f"Còn {remaining} khung khác. " if remaining > 0 and invite is None else ""
    if prefix in (SLOT_AMBIGUOUS, SLOT_AMBIGUOUS_AGAIN) and len(moments) == 2:
        contrast = _contrast(moments[0], moments[1])
        if prefix == SLOT_AMBIGUOUS_AGAIN:
            return f"{prefix}anh chị chọn {contrast[1]} hay {contrast[2]} ạ?"
        if contrast[0]:
            return f"{contrast[0]} em còn {contrast[1]} và {contrast[2]}. {more}{contrast[3]}"
    options = "; ".join(
        f"khung {index + 1}: "
        + (
            f"{_speak_time(moment)} cùng ngày"
            if index > 0 and moment.date() == moments[index - 1].date()
            else speak_datetime(slots[index]["starts_at"])
        )
        for index, moment in enumerate(moments)
    )
    if invite is not None:
        other_day = "đổi sang ngày khác" if invite == "RESCHEDULE" else "đặt vào ngày khác"
        lead = ("Gần nhất có", "Em còn", "Em tìm được", "Em có")[VARIANT_IDS.index(variant)]
        question = (
            f"Anh chị chọn giờ này hay muốn {other_day} ạ?"
            if len(slots) == 1
            else f"Anh chị chọn khung nào, hoặc muốn {other_day} ạ?"
        )
    else:
        lead = (
            "Gần nhất có" if full_date is not None else "Hiện còn",
            "Em còn",
            "Em tìm được",
            "Em có",
        )[VARIANT_IDS.index(variant)]
        question = (
            "Anh chị chọn giờ này không ạ?" if len(slots) == 1 else "Anh chị chọn khung nào ạ?"
        )
    full = f"{_full(full_date)} " if full_date is not None else ""
    return f"{prefix}{full}{lead} {options}. {more}{question}"


def _contrast(first: datetime, second: datetime) -> tuple[str, str, str, str]:
    """(phần chung, khung 1, khung 2, câu hỏi) — nêu đúng chỗ hai khung khác nhau (B9, R-42 c).

    "3 giờ chiều thứ Tư" / "ngày 14" / "ngày 21 tháng 10" / "chọn ngày nào". Phần chung rỗng khi hai khung
    khác cả ngày lẫn giờ: khi đó đọc đủ từng khung.
    """
    if first.date() == second.date():
        common = _speak_date(first)
        return (
            common[0].upper() + common[1:],
            _speak_time(first),
            _speak_time(second),
            ("Anh chị chọn giờ nào ạ?"),
        )
    if (first.hour, first.minute) == (second.hour, second.minute):
        same_weekday = first.weekday() == second.weekday()
        common = _speak_time(first) + (f" {_WEEKDAYS[first.weekday()]}" if same_weekday else "")
        days = _day_pair(first, second, with_weekday=not same_weekday)
        return common, days[0], days[1], "Anh chị chọn ngày nào ạ?"
    return "", speak_datetime(first.isoformat()), speak_datetime(second.isoformat()), ""


def _day_pair(first: date, second: date, *, with_weekday: bool) -> tuple[str, str]:
    """ "ngày 14" / "ngày 21 tháng 10" — tháng chỉ nói một lần khi hai ngày cùng tháng."""

    def day(moment: date, month: bool) -> str:
        weekday = f"{_WEEKDAYS[moment.weekday()]} " if with_weekday else ""
        return f"{weekday}ngày {moment.day}" + (f" tháng {moment.month}" if month else "")

    return day(first, first.month != second.month), day(second, True)


def _full(day: date) -> str:
    spoken = _speak_date(day)
    return f"{spoken[0].upper()}{spoken[1:]} đã kín lịch."


@renderer(
    "ASK_DATE_AGAIN",
    discloses=True,
    str_args={"issue": DATE_ISSUES, "action": SLOT_ACTIONS},
)
def ask_date_again(ctx: CallContext, issue: str, action: str, day: Optional[date] = None) -> str:
    """Ngày người gọi nói không dùng được (R-30, GC-DATE-03): nói đúng lý do rồi hỏi lại, không đoán.

    `day` là ngày người gọi nói (đã qua / trùng hôm nay), không phải dữ liệu lịch hẹn. Khai báo
    `discloses` như mọi câu hỏi đưa vào ask() (đọc lại khi im lặng, R-01 §3.2).
    """
    guardrails.assert_can_disclose(ctx)
    verb = "đổi sang" if action == "RESCHEDULE" else "đặt vào"
    ask_day = f"Anh chị muốn {verb} ngày nào ạ?"
    if issue == "PAST" and day is not None:
        spoken = _speak_date(day)
        return f"{spoken[0].upper()}{spoken[1:]} đã qua rồi ạ. {ask_day}"
    if issue == "TODAY" and day is not None:
        weekday = _WEEKDAYS[day.weekday()]
        return (
            f"Hôm nay là {_speak_date(day)}. Anh chị muốn {verb} hôm nay hay {weekday} tuần sau ạ?"
        )
    if issue == "INVALID":
        return f"Ngày đó không có trong lịch ạ. {ask_day}"
    return f"Anh chị muốn {verb} ngày nào cụ thể ạ?"


@renderer(
    "SLOT_OFFER_READBACK",
    discloses=True,
    sources={"slot": "SLOT"},
    str_args={"prefix": SLOT_PREFIXES, "action": SLOT_ACTIONS, "variant": ("v0",)},
    slot_scope="SELECTED",
)
def slot_offer_readback(
    ctx: CallContext,
    slot: dict[str, Any],
    action: str,
    prefix: str = "",
    full_date: Optional[date] = None,
    *,
    variant: str = "v0",
) -> str:
    """Chỉ còn một khung phù hợp: đọc và hỏi có/không luôn, không hỏi "chọn khung nào" (Hình 0)."""
    guardrails.assert_can_disclose(ctx)
    verb = "đổi sang" if action == "RESCHEDULE" else "đặt"
    full = f"{_full(full_date)} " if full_date is not None else ""
    when = speak_datetime(slot["starts_at"])
    return f"{prefix}{full}Em còn khung {when}. Anh chị {verb} giờ đó nhé ạ?"


@renderer(
    "SLOT_READBACK",
    discloses=True,
    sources={"slot": "SLOT"},
    str_args={"action": SLOT_ACTIONS, "variant": ("v0",)},
    slot_scope="SELECTED",
)
def slot_readback(
    ctx: CallContext, slot: dict[str, Any], action: str = "RESCHEDULE", *, variant: str = "v0"
) -> str:
    """Đọc lại giờ + thứ + ngày + cơ sở của khung đã chọn; không đọc khoa (T-10 V-6)."""
    guardrails.assert_can_disclose(ctx)
    what = "đổi lịch sang" if action == "RESCHEDULE" else "đặt lịch"
    return (
        f"Em xác nhận {what} {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)}. "
        "Anh chị đồng ý chứ ạ?"
    )


@renderer(
    "SLOT_READBACK_DA",
    discloses=True,
    sources={"slot": "SLOT"},
    str_args={"action": SLOT_ACTIONS},
    slot_scope="SELECTED",
)
def slot_readback_da(ctx: CallContext, slot: dict[str, Any], action: str = "RESCHEDULE") -> str:
    """ "dạ" không phải đồng ý (PRD R-23, GC-CONF-01): hỏi lại có/không và nhắc cách trả lời (D-2)."""
    guardrails.assert_can_disclose(ctx)
    what = "đổi lịch sang" if action == "RESCHEDULE" else "đặt lịch"
    return (
        f"Anh chị đồng ý {what} {speak_datetime(slot['starts_at'])} không ạ? "
        "Nếu đồng ý, anh chị nói “đồng ý” giúp em ạ."
    )


@renderer("CANCELLED_DONE", discloses=False, success_outcome="CANCELLED")
def cancelled_done() -> str:
    return DONE_SAFE["CANCELLED"]


@renderer(
    "RESCHEDULED_DONE", discloses=True, success_outcome="RESCHEDULED", sources={"slot": "SLOT"}
)
def rescheduled_done(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Em đã đổi lịch khám sang {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)} cho anh chị ạ."


@renderer("BOOKED_DONE", discloses=True, success_outcome="BOOKED", sources={"slot": "SLOT"})
def booked_done(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Em đã đặt lịch {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)} cho anh chị ạ."


# Nhắc im lặng rồi hỏi lại nguyên văn câu đang chờ (T-08). Metadata thật lấy theo câu bên trong:
# guard chỉ nhận câu này khi `question_text` đúng là câu hỏi của lượt trước (R-01 §3.2).
@renderer("SILENCE_REPROMPT", discloses=True)
def silence_reprompt(question_text: str) -> str:
    return f"{SILENCE} {question_text}"


def clinic_name(appointment: dict[str, Any]) -> str:
    return (
        appointment.get("clinic_name")
        or CLINIC_NAMES.get(appointment.get("clinic_id") or "")
        or "Vinmec"
    )


def _department(appointment: dict[str, Any]) -> str:
    department = appointment.get("department")
    return f"{department} " if department else ""
