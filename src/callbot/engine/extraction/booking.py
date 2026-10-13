"""Luật riêng của luồng đặt lịch inbound (plan `t11-booking-inbound-2026-10-13.md`).

Contract Bảng 1: inbound chỉ có kịch bản đặt lịch mới. Ví dụ Book (Hình 0) hỏi "khoa nào và khoảng thời
gian nào". Mock không nhận khoa (`POST /appointments` chỉ có patient_id, slot_id): khoa chỉ giúp hiểu câu
khách nói, không lọc khung và bot không nhắc lại (D-5).

Chỉ là cụm luật, không quyết định gì: Dialogue / Policy chọn hành động.
"""

import re
from datetime import datetime

from callbot.engine.extraction.agreement import without_fallback_lead
from callbot.engine.extraction.intent import extract_intent
from callbot.engine.extraction.schema import Intent
from callbot.engine.extraction.slot_choice import parse_slot_criteria
from callbot.engine.extraction.text import clean, compile_phrases, find_phrase, strip_diacritics

# Khoa / dịch vụ khám người gọi tự nêu ("Khám tổng quát", "Nội tổng quát, tuần sau được không?")
_DEPARTMENTS = compile_phrases(
    [
        "tổng quát",
        "nội tổng quát",
        "nội khoa",
        "ngoại khoa",
        "tiêu hóa",
        "tiêu hoá",
        "tim mạch",
        "da liễu",
        "sản phụ khoa",
        "sản khoa",
        "phụ khoa",
        "nhi khoa",
        "khoa nhi",
        "cơ xương khớp",
        "xương khớp",
        "thần kinh",
        "hô hấp",
        "tai mũi họng",
        "răng hàm mặt",
        "nha khoa",
        "nhãn khoa",
        "khám mắt",
        "khám răng",
        "tiết niệu",
        "nội tiết",
        "ung bướu",
        "dinh dưỡng",
        "khám sức khỏe",
        "khám sức khoẻ",
        "chuyên khoa",
    ]
)
# "khám <gì đó>" đứng đầu câu trả lời câu hỏi khoa: "khám mắt", "khám thận"
# "tôi khám chỗ khác rồi" là lý do / câu kể, không phải nêu khoa
_EXAM_LEAD_SOURCE = (
    r"^(?:dạ |vâng |ừ |em ơi |tôi muốn |chị muốn |anh muốn |cho tôi |cho chị |cho em )*"
    r"khám (?!chỗ|ở|rồi|xong|bên|tại|lại)\S+"
)

# Để bot chọn khung sớm nhất: "Còn lịch nào gần nhất không em?" (qc-ib-01), "sớm nhất", "lúc nào cũng được"
_EARLIEST = compile_phrases(
    [
        "gần nhất",
        "sớm nhất",
        "càng sớm càng tốt",
        "nhanh nhất",
        "lúc nào cũng được",
        "khi nào cũng được",
        "hôm nào cũng được",
        "ngày nào cũng được",
        "giờ nào cũng được",
        "lịch nào cũng được",
        "khung nào cũng được",
        "tùy em",
        "tuỳ em",
        "em chọn giúp",
    ]
)

# §1.1.9: không tạo bệnh nhân. "đăng ký khám" vẫn là đặt lịch, nên chỉ nhận cụm nói về hồ sơ / đăng ký mới
_NEW_PROFILE = compile_phrases(
    [
        "tạo hồ sơ",
        "tạo mới",
        "lập hồ sơ",
        "mở hồ sơ",
        "làm hồ sơ",
        "đăng ký hồ sơ",
        "đăng ký mới",
        "chưa có hồ sơ",
        "tạo tài khoản",
        "đăng ký tài khoản",
    ]
)

# Đặt hộ người khác (D-7, Bảng 1 "bệnh nhân gọi đến"): người thân + đại từ sở hữu, để "đặt cho chị 8 giờ"
# (chị = chính người gọi, qc-ib-07) không bị tính
_RELATIVE = r"(?:mẹ|bố|ba|má|con|con trai|con gái|vợ|chồng|ông|bà|em|anh|chị|cháu|bạn)"
_OWNER = r"(?:tôi|em|mình|tớ|của tôi|của em|của mình)"
_FOR_OTHER_SOURCES = [
    rf"(?<!\w)(?:cho|giúp|hộ|giùm) {_RELATIVE} {_OWNER}(?!\w)",
    rf"(?<!\w){_RELATIVE} {_OWNER} (?:muốn|cần|định|sẽ) (?:khám|đặt|đi khám)(?!\w)",
]
_FOR_OTHER = [re.compile(source) for source in _FOR_OTHER_SOURCES]
_FOR_OTHER_UNACCENTED = [re.compile(strip_diacritics(source)) for source in _FOR_OTHER_SOURCES]

# Bỏ đặt lịch ở câu mời khung (G7, PRD R-10, GC-BOOK-03 "Giờ khác không được" — qc-ib-06)
_OTHER_TIMES_REFUSED_SOURCE = (
    r"(?<!\w)(?:giờ|ngày|hôm|buổi|khung|lịch|lúc) khác (?:thì )?(?:(?:tôi|em|chị|anh|mình) )?"
    r"(?:không|ko|chẳng|cũng không)(?: (?:đi|đến|tới|khám))? được(?!\w)"
)
_STOP_BOOKING = compile_phrases(
    [
        "chỉ đi được giờ đó",
        "chỉ được giờ đó",
        "không đặt nữa",
        "khỏi đặt",
        "thôi không đặt",
        "không cần đặt nữa",
        "thôi khỏi đặt",
    ]
)

# Đồng ý đúng khung vừa mời bằng câu có/không (G15, R-23): "Không có thì giờ em vừa nói cũng được" (qc-ib-07),
# "giờ đó cũng được", "khung đó đi". Chỉ khi câu không nêu giờ / khung nào khác.
_OFFERED_AGREE_SOURCE = (
    r"^(?:(?:thôi|vậy|thế|ừ|ờ|vâng|dạ|ok|oke|được|thì) )*"
    r"(?:giờ|khung|lịch|cái|lúc) (?:em vừa nói|em vừa đọc|vừa nói|vừa đọc|vừa rồi|đó|này|ấy|kia)"
    r"(?: (?:cũng|thì|là|em))*"
    r" (?:được|ok|oke|đi|đặt luôn|đặt đi|đặt giúp)(?: (?:rồi|luôn|đi|nhé|nha|ạ|em|chị|anh|tôi|giúp|cho))*$"
)


def _both(source: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """(bản có dấu, bản không dấu) của một mẫu: ASR có lúc trả văn bản không dấu."""
    return re.compile(source), re.compile(strip_diacritics(source))


_EXAM_LEAD = _both(_EXAM_LEAD_SOURCE)
_OTHER_TIMES_REFUSED = _both(_OTHER_TIMES_REFUSED_SOURCE)
_OFFERED_AGREE = _both(_OFFERED_AGREE_SOURCE)


def _search(
    patterns: tuple[re.Pattern[str], re.Pattern[str]], text: str, *, whole: bool = False
) -> bool:
    accented, unaccented = patterns
    pattern = unaccented if strip_diacritics(text) == text else accented
    return (pattern.match(text) if whole else pattern.search(text)) is not None


def existing_appointment_request(text: str) -> bool:
    """Việc với lịch có sẵn (hủy / đổi / xác nhận) mà không có cụm đặt lịch: inbound chỉ có đặt lịch mới
    (Bảng 1, G22). `text` phải là phần câu ngoài tên và ngày sinh ("Trần Văn Hủy" không phải yêu cầu hủy)."""
    other = (Intent.CANCEL, Intent.RESCHEDULE, Intent.CONFIRM)
    return (
        extract_intent(text, "inbound", other).found
        and not extract_intent(text, "inbound", (Intent.BOOK,)).found
    )


def mentions_department(transcript: str) -> bool:
    text = clean(transcript)
    return find_phrase(text, _DEPARTMENTS, mixed=True) is not None or _search(
        _EXAM_LEAD, text, whole=True
    )


def asks_earliest(transcript: str) -> bool:
    return find_phrase(clean(transcript), _EARLIEST, mixed=True) is not None


def names_a_time(transcript: str, now: datetime) -> bool:
    """Câu có tiêu chí thời gian (ngày, thứ, buổi, giờ) — không tính thứ tự "khung 2"."""
    criteria = parse_slot_criteria(transcript, now)
    return any(
        value is not None
        for value in (
            criteria.hours,
            criteria.period,
            criteria.weekday,
            criteria.day,
            criteria.month,
            criteria.date_from,
            criteria.date_issue,
            criteria.not_before,
            criteria.before,
        )
    )


def booking_answer(transcript: str, now: datetime) -> bool:
    """Câu trả lời câu hỏi nhu cầu inbound là nhu cầu đặt lịch: nêu giờ, khoa, hoặc để bot chọn khung sớm
    nhất (Bảng 1: inbound chỉ có đặt lịch)."""
    return (
        names_a_time(transcript, now)
        or mentions_department(transcript)
        or asks_earliest(transcript)
    )


def asks_new_profile(transcript: str) -> bool:
    return find_phrase(clean(transcript), _NEW_PROFILE, mixed=True) is not None


def books_for_other(transcript: str) -> bool:
    text = clean(transcript)
    patterns = _FOR_OTHER_UNACCENTED if strip_diacritics(text) == text else _FOR_OTHER
    return any(pattern.search(text) for pattern in patterns)


def refuses_other_times(transcript: str) -> bool:
    text = clean(transcript)
    return (
        _search(_OTHER_TIMES_REFUSED, text)
        or find_phrase(text, _STOP_BOOKING, mixed=True) is not None
    )


def agrees_to_offered(transcript: str) -> bool:
    text = clean(without_fallback_lead(transcript))
    return bool(text) and _search(_OFFERED_AGREE, text, whole=True)


__all__ = [
    "agrees_to_offered",
    "asks_earliest",
    "asks_new_profile",
    "booking_answer",
    "books_for_other",
    "existing_appointment_request",
    "mentions_department",
    "names_a_time",
    "refuses_other_times",
]
