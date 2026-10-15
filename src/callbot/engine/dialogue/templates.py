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

# [R-26] Cụm công bố trợ lý ảo AI. Từ bản câu thoại 13/10/2026 câu chào không còn nói cụm này
# (câu chào ngắn, contract không yêu cầu); giữ hằng để tham chiếu.
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
    "Em chào anh chị, em gọi từ bệnh viện để xác nhận lịch khám. Anh chị cho em xin họ tên ạ?",
)
GREETING_INBOUND = static("GREETING_INBOUND", "Bệnh viện xin nghe. Anh chị cho em xin họ tên ạ?")
# Không có dữ liệu xác minh: chỉ chào, không hỏi tên; lượt 1 nói lý do rồi chuyển máy (LOOKUP_TRANSFER).
GREETING_HANDOFF_INBOUND = static("GREETING_HANDOFF_INBOUND", "Bệnh viện xin nghe ạ.")
# Inbound tra hồ sơ theo số gọi đến không được (chưa hỏi danh tính): nói lý do khi chuyển máy
# (§1.1.9). Khác IDENTITY_FAILED_TRANSFER: đã hỏi tên + ngày sinh thì không nói yếu tố nào sai.
LOOKUP_TRANSFER: dict[str, str] = {
    "NO_PHONE": static(
        "LOOKUP_TRANSFER_NO_PHONE",
        "Em chưa nhận được số điện thoại anh chị đang gọi, nên em chuyển sang nhân viên tư vấn. "
        "Anh chị giữ máy chút nhé.",
    ),
    "NO_CANDIDATES": static(
        "LOOKUP_TRANSFER_NO_CANDIDATES",
        "Em chưa tìm thấy hồ sơ theo số anh chị đang gọi, nên em chuyển sang nhân viên tư vấn. "
        "Anh chị giữ máy chút nhé.",
    ),
    "UNAVAILABLE": static(
        "LOOKUP_TRANSFER_UNAVAILABLE",
        "Hệ thống tra cứu đang gặp sự cố, nên em chuyển sang nhân viên tư vấn. "
        "Anh chị giữ máy chút nhé.",
    ),
}
# Trả lời "alo"/"ai đấy" ở bước hỏi tên. Gọi ra nói lý do gọi ("lịch khám" chung chung, không chi
# tiết — SF-03); gọi vào khách đã biết mình gọi đâu.
GREETING_BACK_OUTBOUND = _static_group(
    "GREETING_BACK_OUTBOUND",
    "Em gọi từ bệnh viện để xác nhận lịch khám. Cho em xin họ tên ạ?",
    "Bệnh viện đây, em gọi về lịch khám của anh chị. Mình tên đầy đủ là gì ạ?",
    "Bên em là bệnh viện, gọi xác nhận lịch khám. Anh chị cho em xin họ tên nhé?",
)
GREETING_BACK_INBOUND = _static_group(
    "GREETING_BACK_INBOUND",
    "Bệnh viện đây. Anh chị cho em xin họ tên ạ?",
    "Bên em là bệnh viện. Cho em xin họ tên của mình nhé?",
    "Anh chị đang gọi tới bệnh viện. Mình tên đầy đủ là gì ạ?",
)
# Tên cũ, giữ cho script nghe thử (tts_fidelity_audit) đang tham chiếu.
GREETING_BACK_SHARED = GREETING_BACK_OUTBOUND
ASK_NAME_AGAIN = _static_group(
    "ASK_NAME_AGAIN",
    "Em nghe chưa rõ tên. Anh chị nhắc lại họ tên đầy đủ giúp em được không ạ?",
    "Xin lỗi anh chị, em chưa nghe kịp tên. Mình nói chậm lại giúp em nhé.",
    "Anh chị đọc lại giúp em cả họ và tên đầy đủ ạ.",
)
# Đã có ngày sinh: xin thêm tên, không nhắc lại ngày sinh hoặc nói khách đã cung cấp tên.
ASK_NAME_AFTER_DOB = _static_group(
    "ASK_NAME_AFTER_DOB",
    "Em cảm ơn. Còn họ tên đầy đủ của mình là gì ạ?",
    "Anh chị cho em xin thêm họ tên đầy đủ ạ.",
    "Vâng, cho em biết thêm họ tên đầy đủ của anh chị nhé.",
)
ASK_NAME_VERIFY_SHARED = _static_group(
    "ASK_NAME_VERIFY_SHARED",
    "Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. "
    "Anh chị cho em xin họ và tên đầy đủ ạ.",
    "Thông tin lịch khám là thông tin riêng, nên anh chị cho em xin họ tên đầy đủ trước "
    "để em tìm đúng hồ sơ ạ.",
    "Em hỗ trợ anh chị ngay sau khi tìm đúng hồ sơ. Cho em xin họ tên đầy đủ của mình ạ.",
)
ASK_NAME_FOR_REQUEST = ASK_NAME_VERIFY_FIRST = ASK_NAME_VERIFY_SHARED
ASK_DOB_VERIFY_SHARED = _static_group(
    "ASK_DOB_VERIFY_SHARED",
    "Để bảo mật thông tin, em cần xác minh trước khi hỗ trợ. "
    "Anh chị cho em xin ngày, tháng, năm sinh ạ.",
    "Thông tin lịch khám là thông tin riêng, nên anh chị cho em xin thêm ngày tháng năm sinh "
    "để em tìm đúng hồ sơ ạ.",
    "Em hỗ trợ anh chị ngay sau khi tìm đúng hồ sơ. Cho em xin ngày tháng năm sinh của mình ạ.",
)
ASK_DOB_FOR_REQUEST = ASK_DOB_VERIFY_FIRST = ASK_DOB_VERIFY_SHARED
# Chưa có call site: giữ một mẫu mỗi tình huống, hoãn thu; không xoá nhánh dự phòng.
ASK_NAME_DECLINED = static(
    "ASK_NAME_DECLINED",
    "Em hiểu. Vì lịch khám là thông tin riêng, em cần họ tên đầy đủ của anh chị mới hỗ trợ "
    "tiếp được. Anh chị cho em xin nhé.",
)
ASK_DOB_INVALID = static(
    "ASK_DOB_INVALID",
    "Ngày này em nghe chưa đúng lắm. Anh chị cho em xin lại ngày tháng năm sinh theo dương lịch ạ.",
)
ASK_DOB_DECLINED = static(
    "ASK_DOB_DECLINED",
    "Em hiểu. Vì lịch khám là thông tin riêng, em cần ngày tháng năm sinh của anh chị mới hỗ trợ "
    "tiếp được. Anh chị cho em xin nhé.",
)
ASK_DOB = _static_group(
    "ASK_DOB",
    "Em cảm ơn. Anh chị cho em xin ngày tháng năm sinh ạ.",
    "Anh chị sinh ngày tháng năm nào ạ?",
    "Cho em xin thêm ngày tháng năm sinh của mình nhé.",
)
INTRODUCE_AGAIN_ASK_DOB = _static_group(
    "INTRODUCE_AGAIN_ASK_DOB",
    "Bệnh viện đây. Anh chị cho em xin ngày tháng năm sinh ạ?",
    "Bên em là bệnh viện. Anh chị sinh ngày tháng năm nào ạ?",
    "Em bên bệnh viện. Cho em xin ngày tháng năm sinh của mình nhé?",
)
ASK_DOB_AGAIN = _static_group(
    "ASK_DOB_AGAIN",
    "Em nghe chưa rõ ngày sinh. Anh chị nhắc lại giúp em được không ạ?",
    "Xin lỗi, em nghe chưa kịp. Anh chị nói chậm lại ngày tháng năm sinh giúp em nhé.",
    "Anh chị nói lại giúp em đủ cả ngày, tháng và năm sinh ạ.",
)
ASK_INTENT_INBOUND = _static_group(
    "ASK_INTENT_INBOUND",
    "Em cảm ơn. Em có thể giúp gì cho anh chị ạ?",
    "Em tìm thấy hồ sơ của mình rồi. Anh chị cần em hỗ trợ gì ạ?",
    "Cảm ơn anh chị. Hôm nay mình muốn đặt lịch khám, hay cần hỗ trợ việc gì khác ạ?",
)
ASK_CHANGE_OR_CANCEL = _static_group(
    "ASK_CHANGE_OR_CANCEL",
    "Vậy anh chị muốn đổi sang hôm khác, hay hủy lịch này ạ?",
    "Vâng, mình muốn dời lịch sang hôm khác, hay hủy luôn ạ?",
    "Anh chị muốn đổi giờ khám khác, hay hủy lịch khám này ạ?",
)
# Mảnh câu đi kèm đọc lịch, không thu riêng thay nguyên utterance.
ASK_ATTENDANCE = "Hôm đó mình đến khám được không ạ?"
NOT_UNDERSTOOD = _static_group(
    "NOT_UNDERSTOOD",
    "Em chưa hiểu rõ ý anh chị, mình nói lại giúp em nhé.",
    "Anh chị nói rõ hơn một chút giúp em được không ạ?",
    "Xin lỗi, em nghe chưa rõ lắm. Anh chị nhắc lại giúp em ạ.",
)
SILENCE = static("SILENCE", "Alo, anh chị có nghe em nói không ạ?")
HOLD = _static_group(
    "HOLD",
    "Dạ vâng, em chờ anh chị.",
    "Anh chị cứ từ từ, em vẫn đang giữ máy.",
    "Không sao ạ, em đợi anh chị.",
)
# Hủy luôn cần hai lượt riêng; giữ câu hỏi xác nhận và từ khoá hủy tường minh.
CANCEL_RECONFIRM = static(
    "CANCEL_RECONFIRM", "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
)
CONFIRM_CONFLICT = static(
    "CONFIRM_CONFLICT",
    "Em hỏi lại cho chắc: anh chị vẫn đến khám theo lịch này, đúng không ạ?",
)
CANCEL_CONFLICT = static(
    "CANCEL_CONFLICT",
    "Anh chị có chắc chắn muốn hủy lịch khám này không ạ? "
    "Nếu đồng ý, anh chị nói “hủy lịch” giúp em ạ.",
)
SLOT_CONFLICT = static("SLOT_CONFLICT", "Anh chị có đồng ý với khung giờ vừa đọc không ạ?")
CANCEL_CHOICE = static(
    "CANCEL_CHOICE",
    "Anh chị muốn hủy lịch, hay vẫn giữ lịch ạ? Nếu hủy, anh chị nói giúp em hai chữ “hủy lịch”.",
)
# Ghi nhận lý do không đồng nghĩa đã nhận được xác nhận hủy.
CANCEL_REASON_NOTED = static(
    "CANCEL_REASON_NOTED",
    "Em hiểu rồi. Vậy anh chị muốn hủy lịch khám này, đúng không ạ?",
)
BOOKING_ABANDONED = _static_group(
    "BOOKING_ABANDONED",
    "Vâng, em chưa đặt lịch nào cho anh chị. Mình cần em hỗ trợ gì thêm không ạ?",
    "Em dừng đặt lịch nhé, chưa có lịch nào được tạo. Anh chị cần hỗ trợ việc gì khác không ạ?",
    "Lịch hẹn chưa được tạo. Anh chị còn cần em giúp gì nữa không ạ?",
)
SLOT_TAKEN = "Giờ đó vừa có người đặt. "
SLOT_NO_MATCH = "Giờ đó em chưa thấy trống. "
SLOT_AMBIGUOUS = "Có vài giờ phù hợp với anh chị. "
# Trang mơ hồ đọc lại y hệt: hỏi khách chọn khung nào, nêu đúng chỗ hai khung khác nhau (review 12-10 §6.1)
SLOT_AMBIGUOUS_AGAIN = "Vậy "
SLOT_NOT_IN_PAGE = "Em vừa báo hai giờ thôi. "
SLOT_TWO_AT_A_TIME = "Em báo mỗi lần hai giờ cho dễ nhớ. "
# Khách xin chọn lại ở câu chốt: đọc lại trang vừa chọn (review 12-10 B16)
SLOT_RECHOOSE = "Em đọc lại để anh chị chọn nhé. "
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
        SLOT_RECHOOSE,
    }
)
SLOT_ACTIONS = frozenset({"RESCHEDULE", "BOOK"})
SLOT_INVITES = frozenset({None, *SLOT_ACTIONS})
SLOT_REFUSE_CHOICE: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_REFUSE_CHOICE_RESCHEDULE", "Anh chị muốn nghe thêm giờ khác, hay giữ lịch cũ ạ?"
    ),
    "BOOK": static(
        "SLOT_REFUSE_CHOICE_BOOK", "Anh chị muốn nghe thêm giờ khác, hay thôi chưa đặt lịch ạ?"
    ),
}
SLOT_EXHAUSTED: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_EXHAUSTED_RESCHEDULE",
        "Em đã báo hết các giờ trống phù hợp rồi. Anh chị muốn tìm ngày khác, hay giữ lịch cũ ạ?",
    ),
    "BOOK": static(
        "SLOT_EXHAUSTED_BOOK",
        "Em đã báo hết các giờ trống phù hợp rồi. Anh chị có muốn tìm sang ngày khác không ạ?",
    ),
}
ROUNDS_EXHAUSTED_TRANSFER = static(
    "ROUNDS_EXHAUSTED_TRANSFER",
    "Lịch cũ của anh chị vẫn giữ nguyên. Em chuyển máy sang nhân viên tư vấn để tìm giờ phù hợp hơn, "
    "mình giữ máy giúp em nhé.",
)
# Đặt mới hết vòng: chưa có lịch cũ để nói "giữ nguyên" (G8).
ROUNDS_EXHAUSTED_BOOK_TRANSFER = static(
    "ROUNDS_EXHAUSTED_BOOK_TRANSFER",
    "Em chưa tìm được giờ phù hợp. Em chuyển máy sang nhân viên tư vấn để hỗ trợ mình tìm giờ khác, "
    "anh chị giữ máy một chút nhé.",
)
NO_SLOTS_TRANSFER = static(
    "NO_SLOTS_TRANSFER",
    "Hiện chưa có giờ trống phù hợp. Em chuyển máy sang nhân viên tư vấn để tìm thêm giúp mình, "
    "anh chị giữ máy một chút nhé.",
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
SLOT_TAKEN_ROUNDS_BOOK_TRANSFER = static(
    "SLOT_TAKEN_ROUNDS_BOOK_TRANSFER",
    "Giờ đó vừa có người đặt. Em xin chuyển máy tới nhân viên để tìm giờ phù hợp ạ.",
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
        "Mình muốn dời lịch sang ngày nào, buổi nào ạ?",
        "Anh chị tiện hôm nào để em tìm giờ trống mới ạ?",
    ),
    "BOOK": _static_group(
        "ASK_SLOT_PREFERENCE_BOOK",
        "Anh chị muốn đặt vào ngày nào hoặc buổi nào ạ?",
        "Mình muốn đi khám vào ngày nào, buổi nào ạ?",
        "Anh chị tiện hôm nào để em tìm giờ trống ạ?",
    ),
}
TRANSFER = static(
    "TRANSFER",
    "Em chuyển máy sang nhân viên tư vấn để hỗ trợ mình, anh chị giữ máy giúp em một chút nhé.",
)
# Xác minh không đạt: nói lý do chuyển máy nhưng không nói yếu tố nào sai (§1.1.2), dùng chung cho
# không khớp, không có hồ sơ và nhiều hồ sơ cùng khớp (inbound).
IDENTITY_FAILED_TRANSFER = static(
    "IDENTITY_FAILED_TRANSFER",
    "Em chưa xác minh được thông tin, nên em chuyển máy sang nhân viên tư vấn để hỗ trợ anh chị. "
    "Mình giữ máy giúp em một chút nhé.",
)
# Không để lại chi tiết lịch, không hứa gọi lại khi chưa có scheduler.
GOODBYE_UNREACHABLE = _static_group(
    "GOODBYE_UNREACHABLE",
    "Em không nghe thấy anh chị nói, em xin phép gác máy. Chào anh chị ạ.",
    "Em xin phép gác máy. Chào anh chị ạ.",
    "Em cảm ơn anh chị, em xin phép gác máy ạ.",
)
# Chỉ phát sau receipt thành công; guard vẫn giữ metadata cho từng kết quả.
DONE_SAFE: dict[str, str] = {
    "CONFIRMED": static(
        "CONFIRMED_SAFE",
        "Em đã xác nhận lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ.",
        success_outcome="CONFIRMED",
    ),
    "CANCELLED": static(
        "CANCELLED_SAFE",
        "Em đã hủy lịch khám cho anh chị rồi. Em cảm ơn, chào anh chị ạ.",
        success_outcome="CANCELLED",
    ),
    "RESCHEDULED": static(
        "RESCHEDULED_SAFE",
        "Em đã đổi lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ.",
        success_outcome="RESCHEDULED",
    ),
    "BOOKED": static(
        "BOOKED_SAFE",
        "Em đã đặt lịch khám cho anh chị rồi. Em cảm ơn, hẹn gặp anh chị ạ.",
        success_outcome="BOOKED",
    ),
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
# Tên thương hiệu và id lạ dùng "bệnh viện", không đọc tên chi nhánh.
CLINIC_NAMES = {
    "cl_vinmec": "bệnh viện",
    "c_001": "Phòng khám Đa khoa Trung tâm",
    "c_002": "Phòng khám Đa khoa Cầu Giấy",
}


def greeting(direction: str) -> str:
    """Câu chào mở đầu dùng chung cho mọi transport.

    Nói bên gọi (bệnh viện) rồi [R-02] hỏi tên bằng câu hỏi mở; gọi ra nói "lịch khám" chung chung, không
    chi tiết (SF-03).
    """
    return GREETING_OUTBOUND if direction == "outbound" else GREETING_INBOUND


def greeting_back(direction: str) -> str:
    """Trả lời "ai đấy?" ở bước hỏi tên: giới thiệu lại bên gọi theo chiều gọi rồi hỏi tên."""
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
        f"Em cảm ơn. Anh chị có lịch khám {_department(appointment)}lúc "
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
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
        f"Em đã xác nhận lịch khám {attendance_facts(appointment)} cho anh chị. "
        "Em cảm ơn, hẹn gặp anh chị hôm đó ạ."
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
        f"Vâng, em giữ nguyên lịch cũ: khám {_department(appointment)}lúc "
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    )


@renderer(
    "CURRENT_TIME_CHOICE",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": ("v0",)},
)
def current_time_choice(
    ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0"
) -> str:
    """Khách nêu lại giờ lịch đang đổi khi chọn khung: nói rõ đó là lịch hiện tại, hỏi giữ lịch hay chọn
    giờ khác — không đoán (§1.1.5, review 12-10 B11)."""
    guardrails.assert_can_disclose(ctx)
    return (
        f"{speak_datetime(appointment['starts_at'])} đang là lịch hiện tại của anh chị. "
        "Mình muốn giữ lịch này, hay chọn giờ khác ạ?"
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
    more = f"Ngoài ra còn {remaining} giờ khác nữa. " if remaining > 0 and invite is None else ""
    if prefix in (SLOT_AMBIGUOUS, SLOT_AMBIGUOUS_AGAIN) and len(moments) == 2:
        contrast = _contrast(moments[0], moments[1])
        if prefix == SLOT_AMBIGUOUS_AGAIN:
            return f"{prefix}anh chị chọn {contrast[1]} hay {contrast[2]} ạ?"
        if contrast[0]:
            return f"{contrast[0]} em còn trống {contrast[1]} và {contrast[2]}. {more}{contrast[3]}"
    options = ", và ".join(
        f"{_speak_time(moment)} cùng ngày"
        if index > 0 and moment.date() == moments[index - 1].date()
        else speak_datetime(slots[index]["starts_at"])
        for index, moment in enumerate(moments)
    )
    if invite is not None:
        other_day = "đổi sang ngày khác" if invite == "RESCHEDULE" else "đặt ngày khác"
        lead = ("Gần nhất còn trống", "Em còn trống", "Em tìm được", "Bên em có")[
            VARIANT_IDS.index(variant)
        ]
        question = (
            f"Anh chị lấy giờ này, hay muốn {other_day} ạ?"
            if len(slots) == 1
            else f"Anh chị chọn một trong hai giờ này, hay muốn {other_day} ạ?"
        )
    else:
        lead = (
            "Gần nhất còn trống" if full_date is not None else "Hiện còn trống",
            "Em còn trống",
            "Em tìm được",
            "Bên em có",
        )[VARIANT_IDS.index(variant)]
        question = (
            "Anh chị lấy giờ này được không ạ?" if len(slots) == 1 else "Anh chị chọn giờ nào ạ?"
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
    return f"{spoken[0].upper()}{spoken[1:]} đã kín lịch rồi."


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
    short_verb = "đổi sang" if action == "RESCHEDULE" else "đặt"
    ask_day = f"Anh chị muốn {verb} ngày nào ạ?"
    if issue == "PAST" and day is not None:
        spoken = _speak_date(day)
        return f"{spoken[0].upper()}{spoken[1:]} đã qua rồi. Anh chị muốn {short_verb} hôm nào ạ?"
    if issue == "TODAY" and day is not None:
        weekday = _WEEKDAYS[day.weekday()]
        return (
            f"Hôm nay là {_speak_date(day)}. Anh chị muốn {verb} hôm nay hay {weekday} tuần sau ạ?"
        )
    if issue == "INVALID":
        return f"Ngày đó không có trong lịch ạ. {ask_day}"
    return f"Anh chị muốn {short_verb} cụ thể hôm nào ạ?"


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
    return f"{prefix}{full}Em còn trống {when}. Anh chị {verb} giờ này được không ạ?"


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
    head = (
        "Vậy em đổi lịch của anh chị sang"
        if action == "RESCHEDULE"
        else "Vậy em đặt lịch cho anh chị lúc"
    )
    return (
        f"{head} {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)} nhé. "
        "Anh chị đồng ý không ạ?"
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
        "Nếu đồng ý, anh chị nói giúp em “đồng ý”."
    )


@renderer("CANCELLED_DONE", discloses=False, success_outcome="CANCELLED")
def cancelled_done() -> str:
    return DONE_SAFE["CANCELLED"]


@renderer(
    "RESCHEDULED_DONE", discloses=True, success_outcome="RESCHEDULED", sources={"slot": "SLOT"}
)
def rescheduled_done(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Em đã đổi lịch khám sang {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)} "
        "cho anh chị. Em cảm ơn, hẹn gặp anh chị hôm đó ạ."
    )


@renderer("BOOKED_DONE", discloses=True, success_outcome="BOOKED", sources={"slot": "SLOT"})
def booked_done(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return (
        f"Em đã đặt lịch khám lúc {speak_datetime(slot['starts_at'])}, tại {clinic_name(slot)} "
        "cho anh chị. Em cảm ơn, hẹn gặp anh chị hôm đó ạ."
    )


# Nhắc im lặng rồi hỏi lại nguyên văn câu đang chờ (T-08). Metadata thật lấy theo câu bên trong:
# guard chỉ nhận câu này khi `question_text` đúng là câu hỏi của lượt trước (R-01 §3.2).
@renderer("SILENCE_REPROMPT", discloses=True)
def silence_reprompt(question_text: str) -> str:
    return f"{SILENCE} {question_text}"


def clinic_name(appointment: dict[str, Any]) -> str:
    name = (
        appointment.get("clinic_name")
        or CLINIC_NAMES.get(appointment.get("clinic_id") or "")
        or "bệnh viện"
    )
    # API có thể trả tên thương hiệu kèm chi nhánh; chỉ đổi phần đọc, giữ nguyên dữ liệu Clinic.
    return "bệnh viện" if "vinmec" in name.casefold() else name


def _department(appointment: dict[str, Any]) -> str:
    department = appointment.get("department")
    return f"{department} " if department else ""
