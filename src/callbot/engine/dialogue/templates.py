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

GREETING_OUTBOUND = static(
    "GREETING_OUTBOUND",
    f"Dạ em xin chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Cho em hỏi em đang nói chuyện với anh chị nào ạ?",
)
GREETING_INBOUND = static(
    "GREETING_INBOUND",
    f"Dạ Vinmec xin nghe, em là {AI_DISCLOSURE} của tổng đài. "
    "Anh chị vui lòng cho em biết họ tên đầy đủ ạ?",
)
# Inbound lượt 0 khi tra cứu không có dữ liệu để xác minh: vẫn công bố AI, không hỏi tên,
# không nói lý do ("số này chưa có hồ sơ" cũng là thông tin về hồ sơ). Lượt 1 chuyển máy.
GREETING_HANDOFF_INBOUND = static(
    "GREETING_HANDOFF_INBOUND",
    f"Dạ Vinmec xin nghe, em là {AI_DISCLOSURE} của tổng đài. "
    "Em xin phép chuyển máy tới nhân viên để hỗ trợ anh chị ạ.",
)
# Người nghe máy hỏi "ai đấy?" khi đang hỏi tên: chào lại, nhắc lại AI [R-26] và hỏi tên
GREETING_BACK_OUTBOUND = static(
    "GREETING_BACK_OUTBOUND",
    f"Dạ em chào anh chị ạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Cho em hỏi em đang nói chuyện với anh chị nào ạ?",
)
GREETING_BACK_INBOUND = static(
    "GREETING_BACK_INBOUND",
    f"Dạ em chào anh chị ạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. "
    "Anh chị vui lòng cho em biết họ tên đầy đủ ạ?",
)
ASK_NAME_AGAIN = static("ASK_NAME_AGAIN", "Dạ, anh chị vui lòng cho em xin họ và tên đầy đủ ạ.")
# Đã có ngày sinh, còn thiếu tên. §1.1.2: không nhắc lại ngày sinh người gọi vừa nói.
ASK_NAME_AFTER_DOB = static("ASK_NAME_AFTER_DOB", "Dạ, anh chị cho em xin thêm họ và tên đầy đủ ạ.")
# Người gọi nói nhu cầu trước khi đọc tên: ghi nhận nhưng phải xác minh trước (SF-03)
ASK_NAME_FOR_REQUEST = static(
    "ASK_NAME_FOR_REQUEST",
    "Dạ vâng, để hỗ trợ anh chị, em cần xác minh thông tin trước. "
    "Anh chị cho em xin họ và tên đầy đủ ạ.",
)
ASK_DOB_FOR_REQUEST = static(
    "ASK_DOB_FOR_REQUEST",
    "Dạ vâng, để hỗ trợ anh chị, em cần xác minh thông tin trước. "
    "Anh chị cho em xin ngày tháng năm sinh ạ.",
)
ASK_NAME_DECLINED = static(
    "ASK_NAME_DECLINED",
    "Dạ, em cần họ và tên để xác minh đúng người trước khi hỗ trợ. "
    "Anh chị vui lòng cho em xin họ và tên đầy đủ ạ.",
)
ASK_DOB = static("ASK_DOB", "Dạ, anh chị cho em xin ngày tháng năm sinh ạ.")
INTRODUCE_AGAIN_ASK_DOB = static(
    "INTRODUCE_AGAIN_ASK_DOB",
    f"Dạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em xin ngày tháng năm sinh ạ.",
)
ASK_DOB_AGAIN = static(
    "ASK_DOB_AGAIN",
    "Dạ, em chưa nghe rõ. Anh chị nhắc lại giúp em ngày, tháng, năm sinh ạ.",
)
# dob INVALID (31/02, thiếu năm, năm 2 chữ số mơ hồ, tuổi, âm lịch): không nhắc lại điều người gọi vừa nói
ASK_DOB_INVALID = static(
    "ASK_DOB_INVALID",
    "Dạ, anh chị vui lòng cho em xin đủ ngày, tháng, năm sinh theo dương lịch ạ.",
)
ASK_DOB_DECLINED = static(
    "ASK_DOB_DECLINED",
    "Dạ, em cần ngày tháng năm sinh để xác minh đúng người trước khi hỗ trợ. "
    "Anh chị vui lòng cho em xin ạ.",
)
# Câu hỏi MỞ (ASK_INTENT): "vâng" không phải câu trả lời hợp lệ, không suy ra đặt lịch
ASK_INTENT_INBOUND = static("ASK_INTENT_INBOUND", "Cảm ơn anh chị. Anh chị cần em hỗ trợ gì ạ?")
ASK_CHANGE_OR_CANCEL = static(
    "ASK_CHANGE_OR_CANCEL", "Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?"
)
# Phần đuôi của các câu đọc lịch — không bao giờ nói riêng nên không đăng ký
ASK_ATTENDANCE = "Anh chị có đến khám được theo lịch này không ạ?"
NOT_UNDERSTOOD = static(
    "NOT_UNDERSTOOD", "Dạ, em chưa hiểu ý anh chị. Anh chị nói lại giúp em được không ạ?"
)
SILENCE = static("SILENCE", "Alo, anh chị còn nghe máy không ạ?")
HOLD = static("HOLD", "Dạ, em chờ anh chị ạ.")
CANCEL_RECONFIRM = static(
    "CANCEL_RECONFIRM", "Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?"
)
CONFIRM_CONFLICT = static(
    "CONFIRM_CONFLICT", "Dạ, anh chị có đồng ý xác nhận đến khám theo lịch vừa đọc không ạ?"
)
CANCEL_CONFLICT = static(
    "CANCEL_CONFLICT",
    "Dạ, anh chị có chắc chắn muốn hủy lịch khám này không ạ? "
    "Nếu đồng ý, anh chị nói “hủy lịch” giúp em ạ.",
)
SLOT_CONFLICT = static("SLOT_CONFLICT", "Dạ, anh chị có đồng ý với khung giờ vừa đọc không ạ?")
# Câu lựa chọn A/B khi agreement UNCLEAR (thiết kế §5.6): từ đáp lễ không còn là câu trả lời hợp lệ.
# Nói luôn cụm cần nói, vì ngưỡng AGREE ở đây đòi động từ hủy tường minh (SF-05).
CANCEL_CHOICE = static(
    "CANCEL_CHOICE",
    "Dạ, anh chị muốn hủy hay giữ lịch khám ạ? Nếu muốn hủy, anh chị xác nhận “hủy lịch” giúp em ạ.",
)
# Đã hiểu lý do nhưng người gọi chưa xác nhận hủy (T-05 §3.3). Chỉ đọc tiền tố ghi nhận khi lý do
# đã xác định — không đọc lại lý do phỏng đoán, và ghi nhận lý do KHÔNG phải đã đồng ý hủy.
CANCEL_REASON_NOTED = static(
    "CANCEL_REASON_NOTED",
    "Dạ, em đã ghi nhận lý do. Anh chị xác nhận hủy lịch khám này chứ ạ? "
    "Nếu muốn hủy, anh chị nói “hủy lịch” giúp em ạ.",
)
BOOKING_ABANDONED = static(
    "BOOKING_ABANDONED",
    "Dạ, em chưa đặt lịch nào cho anh chị. Anh chị cần em hỗ trợ gì thêm ạ?",
)
# Tiền tố của câu đề xuất slot — chỉ đi kèm `offer_slots` / `slot_offer_readback`, không nói riêng
SLOT_TAKEN = "Dạ, khung giờ đó vừa có người đặt. "
SLOT_NO_MATCH = "Dạ, em chưa thấy khung giờ đó. "
SLOT_AMBIGUOUS = "Dạ, có nhiều khung giờ phù hợp. "
# Người gọi chọn "khung 3" khi bot mới đọc 2 khung (R-25): nói rõ rồi đọc lại trang (T-10)
SLOT_NOT_IN_PAGE = "Dạ, em vừa đọc hai khung thôi ạ. "
# Người gọi xin nghe hơn 2 khung một lượt ("cho xem 4 khung khác"): vẫn đọc 2 (R-25), nói lý do
SLOT_TWO_AT_A_TIME = "Dạ, em đọc lần lượt hai khung một để anh chị dễ nhớ ạ. "
# Miền giá trị riêng của `prefix` (R-01 §3.2): không phải hằng đã đăng ký bất kỳ, nếu không một câu
# báo thành công dùng làm prefix sẽ lọt qua kiểm tra lời báo thành công
SLOT_PREFIXES = frozenset(
    {"", SLOT_TAKEN, SLOT_NO_MATCH, SLOT_AMBIGUOUS, SLOT_NOT_IN_PAGE, SLOT_TWO_AT_A_TIME}
)
# Hành động của câu đọc slot: đổi lịch (outbound) hay đặt lịch (inbound)
SLOT_ACTIONS = frozenset({"RESCHEDULE", "BOOK"})
# Câu mời nêu ngày khác (D-1): không mời, hoặc mời theo hành động
SLOT_INVITES = frozenset({None, *SLOT_ACTIONS})
# "không" trần ở bước chọn slot: không đoán là bỏ đổi lịch, hỏi A/B (T-10 Q-4)
SLOT_REFUSE_CHOICE: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_REFUSE_CHOICE_RESCHEDULE", "Dạ, anh chị muốn nghe khung khác hay giữ lịch cũ ạ?"
    ),
    "BOOK": static(
        "SLOT_REFUSE_CHOICE_BOOK", "Dạ, anh chị muốn nghe khung khác hay thôi không đặt lịch ạ?"
    ),
}
# Đã đọc / bị từ chối hết khung của yêu cầu hiện tại (T-10 §3.2)
SLOT_EXHAUSTED: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_EXHAUSTED_RESCHEDULE",
        "Dạ, em đã đọc hết khung trống phù hợp. Anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?",
    ),
    "BOOK": static(
        "SLOT_EXHAUSTED_BOOK",
        "Dạ, em đã đọc hết khung trống phù hợp. Anh chị muốn đặt vào ngày khác không ạ?",
    ),
}
# Hết 2 vòng (R-29, GC-RES-05): giữ lịch cũ, không ghi gì, chuyển nhân viên PATIENT_REQUEST
ROUNDS_EXHAUSTED_TRANSFER = static(
    "ROUNDS_EXHAUSTED_TRANSFER",
    "Dạ, em giữ nguyên lịch cũ của anh chị và xin phép chuyển máy cho nhân viên để tìm giờ phù hợp ạ.",
)
# Clinic không còn khung trống nào (T-10 D-4): nói lý do rồi chuyển máy
NO_SLOTS_TRANSFER = static(
    "NO_SLOTS_TRANSFER",
    "Dạ, hiện em không còn khung trống nào. Em xin phép chuyển máy cho nhân viên hỗ trợ anh chị ạ.",
)
# Khung vừa chốt có người khác đặt (G-7) mà không còn khung nào để đọc tiếp: vẫn phải nói khung đó
# không đặt được, nếu không người gọi vừa nói "đồng ý" sẽ tưởng đã đổi / đặt xong
SLOT_TAKEN_EXHAUSTED: dict[str, str] = {
    "RESCHEDULE": static(
        "SLOT_TAKEN_EXHAUSTED_RESCHEDULE",
        "Dạ, khung giờ đó vừa có người đặt và em không còn khung phù hợp khác. "
        "Anh chị muốn đổi sang ngày khác hay giữ lịch cũ ạ?",
    ),
    "BOOK": static(
        "SLOT_TAKEN_EXHAUSTED_BOOK",
        "Dạ, khung giờ đó vừa có người đặt và em không còn khung phù hợp khác. "
        "Anh chị muốn đặt vào ngày khác không ạ?",
    ),
}
SLOT_TAKEN_ROUNDS_TRANSFER = static(
    "SLOT_TAKEN_ROUNDS_TRANSFER",
    "Dạ, khung giờ đó vừa có người đặt. Em giữ nguyên lịch cũ của anh chị và xin phép chuyển máy "
    "cho nhân viên để tìm giờ phù hợp ạ.",
)
SLOT_TAKEN_NO_SLOTS_TRANSFER = static(
    "SLOT_TAKEN_NO_SLOTS_TRANSFER",
    "Dạ, khung giờ đó vừa có người đặt và hiện em không còn khung trống nào. "
    "Em xin phép chuyển máy cho nhân viên hỗ trợ anh chị ạ.",
)
# Lý do hỏi lại ngày (R-30): khớp `extraction.schema.DateIssue`
DATE_ISSUES = frozenset({"PAST", "INVALID", "TOO_BROAD", "TODAY"})
# Người gọi muốn ngày khác nhưng chưa nói ngày nào
ASK_SLOT_PREFERENCE: dict[str, str] = {
    "RESCHEDULE": static(
        "ASK_SLOT_PREFERENCE_RESCHEDULE", "Dạ, anh chị muốn đổi sang ngày nào hoặc buổi nào ạ?"
    ),
    "BOOK": static(
        "ASK_SLOT_PREFERENCE_BOOK", "Dạ, anh chị muốn đặt vào ngày nào hoặc buổi nào ạ?"
    ),
}
TRANSFER = static("TRANSFER", "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ.")
# §1.1.7: không để lại chi tiết lịch hẹn trên hộp thư thoại
GOODBYE_UNREACHABLE = static("GOODBYE_UNREACHABLE", "Dạ, em xin phép gọi lại sau ạ. Chào anh chị.")

# Câu báo thành công không chi tiết: Output Guard thay vào khi lượt đã ghi thành công nhưng câu báo
# chi tiết không qua được kiểm tra (R-01 §3.5) — vẫn báo đúng kết quả đã ghi, không chuyển máy
DONE_SAFE: dict[str, str] = {
    "CONFIRMED": static(
        "CONFIRMED_SAFE",
        "Dạ, em đã xác nhận lịch khám cho anh chị. Hẹn gặp anh chị ạ.",
        success_outcome="CONFIRMED",
    ),
    "CANCELLED": static(
        "CANCELLED_SAFE",
        "Dạ, em đã hủy lịch khám cho anh chị ạ.",
        success_outcome="CANCELLED",
    ),
    "RESCHEDULED": static(
        "RESCHEDULED_SAFE",
        "Dạ, em đã đổi lịch khám cho anh chị ạ.",
        success_outcome="RESCHEDULED",
    ),
    "BOOKED": static(
        "BOOKED_SAFE",
        "Dạ, em đã đặt lịch khám cho anh chị ạ.",
        success_outcome="BOOKED",
    ),
    "TRANSFERRED": TRANSFER,
    "UNREACHABLE": GOODBYE_UNREACHABLE,
}

# Câu gốc là v0 để các renderer/test gọi trực tiếp vẫn có một cách nói chuẩn.
# Mỗi câu thay thế cũng đăng ký riêng: guard không nới allow-list cho text tùy ý.
# Xác nhận hủy (CANCEL_*), câu fallback DONE_SAFE và nhắc im lặng giữ nguyên.
STATIC_VARIANTS: dict[str, tuple[str, ...]] = {}
_STATIC_GROUPS: dict[str, str] = {}


def _static_group(group: str, original: str, *alternatives: str) -> None:
    if len(alternatives) != 3 or len({original, *alternatives}) != 4:
        raise ValueError(f"{group} cần đúng bốn câu khác nhau")
    STATIC_VARIANTS[original] = (
        original,
        *(
            static(f"{group}_{variant}", text)
            for variant, text in zip(VARIANT_IDS[1:], alternatives, strict=True)
        ),
    )
    _STATIC_GROUPS[original] = group


_static_group(
    "GREETING_OUTBOUND",
    GREETING_OUTBOUND,
    f"Dạ, em chào anh chị. Em là {AI_DISCLOSURE} của tổng đài Vinmec. Cho em xin họ và tên đầy đủ ạ?",
    f"Xin chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em biết họ tên đầy đủ ạ?",
    f"Dạ, tổng đài Vinmec xin chào. Em là {AI_DISCLOSURE}. Cho em hỏi họ và tên đầy đủ của anh chị ạ?",
)
_static_group(
    "GREETING_INBOUND",
    GREETING_INBOUND,
    f"Dạ, em chào anh chị. Em là {AI_DISCLOSURE} của tổng đài Vinmec. Cho em xin họ và tên đầy đủ ạ?",
    f"Tổng đài Vinmec xin nghe. Em là {AI_DISCLOSURE}. Anh chị cho em biết họ tên đầy đủ ạ?",
    f"Dạ, anh chị đang gặp {AI_DISCLOSURE} của tổng đài Vinmec. Cho em hỏi họ và tên đầy đủ ạ?",
)
_static_group(
    "GREETING_HANDOFF_INBOUND",
    GREETING_HANDOFF_INBOUND,
    f"Dạ, tổng đài Vinmec xin nghe. Em là {AI_DISCLOSURE}. Em xin nối máy với nhân viên để hỗ trợ anh chị ạ.",
    f"Em chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. Em sẽ chuyển máy tới nhân viên hỗ trợ ạ.",
    f"Dạ, em là {AI_DISCLOSURE} của tổng đài Vinmec. Em xin chuyển cuộc gọi tới nhân viên để hỗ trợ tiếp ạ.",
)
_static_group(
    "GREETING_BACK_OUTBOUND",
    GREETING_BACK_OUTBOUND,
    f"Dạ, em nghe anh chị ạ. Em là {AI_DISCLOSURE} của tổng đài Vinmec. Cho em xin họ tên đầy đủ ạ?",
    f"Em chào anh chị, em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em biết họ tên đầy đủ ạ?",
    f"Dạ, đây là {AI_DISCLOSURE} của tổng đài Vinmec. Cho em hỏi họ và tên đầy đủ của anh chị ạ?",
)
_static_group(
    "GREETING_BACK_INBOUND",
    GREETING_BACK_INBOUND,
    f"Dạ, Vinmec xin nghe. Em là {AI_DISCLOSURE} của tổng đài. Cho em xin họ tên đầy đủ ạ?",
    f"Em đang nghe anh chị ạ. Em là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị cho em biết họ tên đầy đủ ạ?",
    f"Dạ, đây là {AI_DISCLOSURE} của tổng đài Vinmec. Anh chị vui lòng cho em xin họ và tên đầy đủ ạ?",
)
_static_group(
    "ASK_NAME_AGAIN",
    ASK_NAME_AGAIN,
    "Dạ, cho em xin lại họ và tên đầy đủ của anh chị ạ.",
    "Em chưa nghe rõ họ tên. Anh chị đọc lại họ và tên đầy đủ giúp em ạ.",
    "Anh chị vui lòng nhắc lại họ và tên đầy đủ để em đối chiếu ạ.",
)
_static_group(
    "ASK_NAME_AFTER_DOB",
    ASK_NAME_AFTER_DOB,
    "Dạ, em xin thêm họ và tên đầy đủ để đối chiếu ạ.",
    "Anh chị cho em biết thêm họ và tên đầy đủ ạ.",
    "Em xin họ và tên đầy đủ của anh chị để tiếp tục xác minh ạ.",
)
_static_group(
    "ASK_NAME_FOR_REQUEST",
    ASK_NAME_FOR_REQUEST,
    "Dạ, em cần xác minh thông tin trước khi hỗ trợ. Cho em xin họ và tên đầy đủ ạ.",
    "Để hỗ trợ đúng người, em xin họ và tên đầy đủ của anh chị trước ạ.",
    "Dạ, mình cần xác minh thông tin trước. Anh chị cho em biết họ và tên đầy đủ ạ.",
)
_static_group(
    "ASK_DOB_FOR_REQUEST",
    ASK_DOB_FOR_REQUEST,
    "Dạ, em cần xác minh thông tin trước khi hỗ trợ. Cho em xin ngày tháng năm sinh ạ.",
    "Để hỗ trợ đúng người, em xin thêm ngày tháng năm sinh của anh chị ạ.",
    "Dạ, mình cần xác minh thông tin trước. Anh chị cho em biết ngày tháng năm sinh ạ.",
)
_static_group(
    "ASK_NAME_DECLINED",
    ASK_NAME_DECLINED,
    "Dạ, em cần họ tên để xác minh trước khi hỗ trợ. Anh chị cho em biết họ và tên đầy đủ ạ.",
    "Để xác minh đúng người, em cần họ và tên đầy đủ. Anh chị vui lòng cung cấp giúp em ạ.",
    "Em cần đối chiếu họ tên trước ạ. Cho em xin họ và tên đầy đủ của anh chị.",
)
_static_group(
    "ASK_DOB",
    ASK_DOB,
    "Dạ, cho em xin ngày tháng năm sinh để đối chiếu ạ.",
    "Em xin thêm ngày tháng năm sinh của anh chị để xác minh thông tin ạ.",
    "Anh chị vui lòng cho em biết ngày tháng năm sinh ạ.",
)
_static_group(
    "INTRODUCE_AGAIN_ASK_DOB",
    INTRODUCE_AGAIN_ASK_DOB,
    f"Dạ, đây là {AI_DISCLOSURE} của tổng đài Vinmec. Cho em xin ngày tháng năm sinh ạ.",
    f"Em là {AI_DISCLOSURE} của tổng đài Vinmec ạ. Anh chị cho em biết ngày tháng năm sinh để đối chiếu ạ.",
    f"Dạ, anh chị đang gặp {AI_DISCLOSURE} của tổng đài Vinmec. Em xin thêm ngày tháng năm sinh ạ.",
)
_static_group(
    "ASK_DOB_AGAIN",
    ASK_DOB_AGAIN,
    "Dạ, em chưa nghe rõ ngày sinh. Anh chị đọc lại đủ ngày, tháng, năm giúp em ạ.",
    "Anh chị nhắc lại ngày tháng năm sinh giúp em ạ, em chưa nghe rõ.",
    "Em xin nghe lại ngày, tháng và năm sinh của anh chị ạ.",
)
_static_group(
    "ASK_DOB_INVALID",
    ASK_DOB_INVALID,
    "Dạ, em cần đủ ngày, tháng và năm sinh theo dương lịch. Anh chị đọc lại giúp em ạ.",
    "Anh chị cho em biết đầy đủ ngày tháng năm sinh theo dương lịch ạ.",
    "Em xin lại ngày, tháng, năm sinh theo dương lịch của anh chị ạ.",
)
_static_group(
    "ASK_DOB_DECLINED",
    ASK_DOB_DECLINED,
    "Dạ, em cần ngày sinh để đối chiếu trước khi hỗ trợ. Cho em xin ngày tháng năm sinh ạ.",
    "Để xác minh đúng người, em cần ngày tháng năm sinh. Anh chị vui lòng cung cấp giúp em ạ.",
    "Em cần đối chiếu thêm ngày sinh ạ. Anh chị cho em biết ngày tháng năm sinh để xác minh ạ.",
)
_static_group(
    "ASK_INTENT_INBOUND",
    ASK_INTENT_INBOUND,
    "Dạ, em đã xác minh xong. Anh chị cần hỗ trợ gì ạ?",
    "Cảm ơn anh chị. Em có thể hỗ trợ việc gì tiếp theo ạ?",
    "Thông tin đã được xác minh ạ. Anh chị muốn em hỗ trợ gì hôm nay?",
)
_static_group(
    "ASK_CHANGE_OR_CANCEL",
    ASK_CHANGE_OR_CANCEL,
    "Anh chị muốn em hỗ trợ đổi lịch hay hủy lịch khám ạ?",
    "Dạ, mình muốn đổi sang lịch khác hay hủy lịch khám này ạ?",
    "Em xin hỏi thêm: anh chị muốn đổi lịch hay hủy lịch ạ?",
)
_static_group(
    "NOT_UNDERSTOOD",
    NOT_UNDERSTOOD,
    "Dạ, em chưa hiểu rõ. Anh chị nói lại giúp em ạ.",
    "Anh chị có thể nói lại ý vừa rồi giúp em không ạ?",
    "Em chưa nắm rõ ý vừa rồi. Anh chị nhắc lại giúp em ạ.",
)
_static_group(
    "HOLD",
    HOLD,
    "Dạ vâng, em chờ ạ.",
    "Anh chị cứ từ từ, em đang chờ ạ.",
    "Dạ, khi nào sẵn sàng anh chị nói tiếp giúp em ạ.",
)
_static_group(
    "TRANSFER",
    TRANSFER,
    "Dạ, em xin nối máy với nhân viên để hỗ trợ tiếp ạ.",
    "Em sẽ chuyển cuộc gọi tới nhân viên hỗ trợ anh chị ạ.",
    "Dạ, để nhân viên hỗ trợ thêm, em xin chuyển máy ạ.",
)
_static_group(
    "GOODBYE_UNREACHABLE",
    GOODBYE_UNREACHABLE,
    "Dạ, em xin kết thúc cuộc gọi và liên hệ lại sau ạ.",
    "Em xin phép gọi lại vào lúc khác ạ. Em chào anh chị.",
    "Dạ, em sẽ liên hệ lại sau. Em xin chào ạ.",
)
_static_group(
    "BOOKING_ABANDONED",
    BOOKING_ABANDONED,
    "Dạ, em chưa tạo lịch hẹn nào. Anh chị cần hỗ trợ gì thêm ạ?",
    "Em chưa đặt lịch ạ. Anh chị muốn em hỗ trợ việc gì tiếp theo?",
    "Dạ, chưa có lịch nào được đặt. Em có thể hỗ trợ gì thêm ạ?",
)
_static_group(
    "ASK_SLOT_PREFERENCE_RESCHEDULE",
    ASK_SLOT_PREFERENCE["RESCHEDULE"],
    "Anh chị cho em biết ngày hoặc buổi muốn đổi lịch sang ạ.",
    "Dạ, em xin ngày hoặc buổi anh chị muốn đổi sang ạ.",
    "Để tìm khung phù hợp, anh chị muốn đổi lịch sang ngày nào hoặc buổi nào ạ?",
)
_static_group(
    "ASK_SLOT_PREFERENCE_BOOK",
    ASK_SLOT_PREFERENCE["BOOK"],
    "Anh chị cho em biết ngày hoặc buổi muốn đặt lịch ạ.",
    "Dạ, em xin ngày hoặc buổi anh chị muốn đặt lịch ạ.",
    "Để tìm khung phù hợp, anh chị muốn đặt lịch vào ngày nào hoặc buổi nào ạ?",
)


def static_choices(original: str) -> tuple[str, ...]:
    """Tập câu đã duyệt cho một hành vi; câu ngoài danh mục giữ nguyên."""
    return STATIC_VARIANTS.get(original, (original,))


def choose_static(ctx: CallContext, original: str) -> str:
    group = _STATIC_GROUPS.get(original)
    if group is None:
        return original
    return STATIC_VARIANTS[original][VARIANT_IDS.index(choose_variant(ctx, group))]


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
    """ "3 giờ 30 chiều thứ Tư ngày 14 tháng 10" — mọi câu xác nhận ngày có thứ (PRD GC-DATE-05)."""
    moment = to_local(datetime.fromisoformat(iso))
    return f"{_speak_time(moment)} {_speak_date(moment)}"


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
    return f"{speak_datetime(appointment['starts_at'])} tại {clinic_name(appointment)}"


@renderer(
    "APPOINTMENT_SUMMARY",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": VARIANT_IDS},
)
def appointment_summary(
    ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0"
) -> str:
    """Figure 0 rev 1.1: tóm tắt + đọc lại ngày, giờ, cơ sở + hỏi đến được không, trong một lượt."""
    guardrails.assert_can_disclose(ctx)
    if variant != "v0":
        return _attendance_variant(appointment, variant, ASK_ATTENDANCE)
    return (
        f"Cảm ơn anh chị. Lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)} ạ. {ASK_ATTENDANCE}"
    )


@renderer(
    "ATTENDANCE_READBACK",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": VARIANT_IDS},
)
def attendance_readback(
    ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0"
) -> str:
    """§1.1.3: đọc lại ngày, giờ, chuyên khoa trước khi CONFIRMED."""
    guardrails.assert_can_disclose(ctx)
    if variant != "v0":
        return _attendance_variant(appointment, variant, "Anh chị đồng ý chứ ạ?")
    return (
        f"Dạ, em xin xác nhận lại: lịch khám {_department(appointment)}"
        f"{attendance_facts(appointment)}. Anh chị đồng ý chứ ạ?"
    )


@renderer(
    "ATTENDANCE_REREAD",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": VARIANT_IDS},
)
def attendance_reread(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    """Câu trả lời chưa rõ: đọc lại (kiến trúc §3.2 "Chưa rõ -> O_READ") bằng câu hỏi có / không —
    "vâng" là câu trả lời hợp lệ, khác câu A/B."""
    guardrails.assert_can_disclose(ctx)
    if variant != "v0":
        return _attendance_variant(appointment, variant, ASK_ATTENDANCE)
    return (
        f"Dạ, lịch khám {_department(appointment)}của anh chị là "
        f"{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    )


@renderer(
    "CANCEL_READBACK",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": VARIANT_IDS},
)
def cancel_readback(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    """§1.1.4: đọc lại lịch sắp hủy rồi hỏi xác nhận lần hai. Câu hỏi cuối giữ nguyên văn
    CANCEL_RECONFIRM; các câu hỏi lại sau đó (CANCEL_CHOICE...) không đọc lại lịch."""
    guardrails.assert_can_disclose(ctx)
    if variant != "v0":
        return _attendance_variant(appointment, variant, CANCEL_RECONFIRM)
    return (
        f"Dạ, lịch khám {_department(appointment)}của anh chị là "
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
        f"Dạ, em đã xác nhận lịch khám {attendance_facts(appointment)} cho anh chị. "
        "Hẹn gặp anh chị ạ."
    )


@renderer(
    "KEEP_APPOINTMENT",
    discloses=True,
    sources={"appointment": "APPOINTMENT"},
    str_args={"variant": VARIANT_IDS},
)
def keep_appointment(ctx: CallContext, appointment: dict[str, Any], *, variant: str = "v0") -> str:
    guardrails.assert_can_disclose(ctx)
    if variant != "v0":
        lead = {
            "v1": "Dạ, lịch cũ vẫn được giữ nguyên:",
            "v2": "Em giữ nguyên lịch cũ và xin đọc lại:",
            "v3": "Lịch cũ được giữ nguyên ạ. Em xin nhắc lại:",
        }[variant]
        return f"{lead} lịch khám {_department(appointment)}{attendance_facts(appointment)}. {ASK_ATTENDANCE}"
    return (
        f"Dạ, em giữ nguyên lịch khám {_department(appointment)}"
        f"{attendance_facts(appointment)} cho anh chị. {ASK_ATTENDANCE}"
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
    options = "; ".join(
        f"khung {i} là {speak_datetime(s['starts_at'])}" for i, s in enumerate(slots, 1)
    )
    if invite is not None:
        other_day = "đổi sang ngày khác" if invite == "RESCHEDULE" else "đặt vào ngày khác"
        lead = (
            "Dạ, lịch trống gần nhất có",
            "Em xin đọc các khung trống gần nhất:",
            "Các khung trống gần nhất là",
            "Dạ, em tìm được các khung trống gần nhất:",
        )[VARIANT_IDS.index(variant)]
        return f"{lead} {options}. Anh chị chọn khung nào, hoặc muốn {other_day} ạ?"
    more = f"Ngoài ra còn {remaining} khung khác. " if remaining > 0 else ""
    if full_date is not None:
        lead = (
            f"{_full(full_date)} "
            + (
                "Gần nhất em còn",
                "Các khung gần nhất là",
                "Em xin đọc các khung gần nhất:",
                "Em tìm được các khung gần nhất:",
            )[VARIANT_IDS.index(variant)]
        )
    else:
        # prefix đã mở bằng "Dạ, " — không lặp "Dạ" lần hai
        lead = (
            "Hiện còn" if prefix else "Dạ, hiện còn",
            "Em xin đọc các khung trống:",
            "Các khung trống hiện có là",
            "Em tìm được các khung trống sau:",
        )[VARIANT_IDS.index(variant)]
    return f"{prefix}{lead} {options}. {more}Anh chị chọn khung nào ạ?"


def _full(day: date) -> str:
    return f"Dạ, {_speak_date(day)} đã kín lịch."


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
        return f"Dạ, {_speak_date(day)} đã qua rồi ạ. {ask_day}"
    if issue == "TODAY" and day is not None:
        weekday = _WEEKDAYS[day.weekday()]
        return f"Dạ, hôm nay là {_speak_date(day)}. Anh chị muốn {verb} hôm nay hay {weekday} tuần sau ạ?"
    if issue == "INVALID":
        return f"Dạ, ngày đó không có trong lịch ạ. {ask_day}"
    return f"Dạ, anh chị cho em xin ngày cụ thể ạ. {ask_day}"


@renderer(
    "SLOT_OFFER_READBACK",
    discloses=True,
    sources={"slot": "SLOT"},
    str_args={"prefix": SLOT_PREFIXES, "action": SLOT_ACTIONS, "variant": VARIANT_IDS},
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
    moment = to_local(datetime.fromisoformat(slot["starts_at"]))
    verb = "đổi sang" if action == "RESCHEDULE" else "đặt"
    when = f"{_period(moment)} {_speak_date(moment)} còn khung {_speak_time(moment)}"
    if full_date is not None:
        lead = f"{_full(full_date)} Gần nhất {when}"
    else:
        lead = when[0].upper() + when[1:] if prefix else f"Dạ, {when}"
    if variant != "v0":
        intro = {
            "v1": "Em xin đọc khung trống này:",
            "v2": "Em xin nhắc lại khung trống:",
            "v3": "Khung trống em tìm được là:",
        }[variant]
        lead = f"{_full(full_date)} {intro} {when}" if full_date is not None else f"{intro} {when}"
    return f"{prefix}{lead}. Anh chị {verb} giờ đó nhé ạ?"


@renderer(
    "SLOT_READBACK",
    discloses=True,
    sources={"slot": "SLOT"},
    str_args={"action": SLOT_ACTIONS, "variant": VARIANT_IDS},
    slot_scope="SELECTED",
)
def slot_readback(
    ctx: CallContext, slot: dict[str, Any], action: str = "RESCHEDULE", *, variant: str = "v0"
) -> str:
    """Đọc lại giờ + thứ + ngày + cơ sở của khung đã chọn; không đọc khoa (T-10 V-6)."""
    guardrails.assert_can_disclose(ctx)
    what = "đổi lịch sang" if action == "RESCHEDULE" else "đặt lịch"
    lead = (
        "Dạ, em xác nhận",
        "Em xin đọc lại yêu cầu",
        "Dạ, em nhắc lại thông tin",
        "Em xin xác nhận lại việc",
    )[VARIANT_IDS.index(variant)]
    return (
        f"{lead} {what} {speak_datetime(slot['starts_at'])} tại {clinic_name(slot)}. "
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
        f"Dạ, anh chị đồng ý {what} {speak_datetime(slot['starts_at'])} không ạ? "
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
    return f"Dạ, em đã đổi lịch khám sang {speak_datetime(slot['starts_at'])} cho anh chị ạ."


@renderer("BOOKED_DONE", discloses=True, success_outcome="BOOKED", sources={"slot": "SLOT"})
def booked_done(ctx: CallContext, slot: dict[str, Any]) -> str:
    guardrails.assert_can_disclose(ctx)
    return f"Dạ, em đã đặt lịch {speak_datetime(slot['starts_at'])} cho anh chị ạ."


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


def _attendance_variant(appointment: dict[str, Any], variant: str, question: str) -> str:
    facts = f"lịch khám {_department(appointment)}{attendance_facts(appointment)}"
    statements = {
        "v1": f"Dạ, em xin đọc lại: {facts}.",
        "v2": f"Em xin nhắc lại thông tin {facts}.",
        "v3": f"Dạ, em xin xác nhận thông tin {facts}.",
    }
    return f"{statements[variant]} {question}"
