"""Intent — thiết kế v1.1 §5.4 (tầng luật viết tay).

Ưu tiên khi một câu khớp nhiều nhãn:
    REQUEST_HUMAN > NOT_PATIENT > OUT_OF_SCOPE > RESCHEDULE > CANCEL > BOOK > CONFIRM > REPEAT_REQUEST

- "Không đến được, đổi sang chiều được không" -> RESCHEDULE (có phương án thay thế).
- Phủ định đứng trước từ khoá hành động bị loại: "không hủy", "đừng đổi", "chưa muốn đặt lịch".
  Không áp dụng cho OUT_OF_SCOPE ("không có bảo hiểm thì sao" vẫn là câu hỏi bảo hiểm).
- Transcript không dấu: khớp bản không dấu của từ khoá, provenance NORMALIZED. Từ khoá mà bản
  không dấu trùng nghĩa khác nằm trong `_UNACCENTED_EXCLUDE` ("dời" / "đợi", "tôi đến" / "tối đến").
"""

import re
from typing import Iterable, Optional

from callbot.engine.extraction.schema import Field, Intent, Provenance
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
    strip_diacritics,
)
from callbot.engine.types import Direction

PRIORITY: tuple[Intent, ...] = (
    Intent.REQUEST_HUMAN,
    Intent.NOT_PATIENT,
    Intent.OUT_OF_SCOPE,
    Intent.RESCHEDULE,
    Intent.CANCEL,
    Intent.BOOK,
    Intent.CONFIRM,
    Intent.REPEAT_REQUEST,
)
# Nhãn chỉ có nghĩa ở bước danh tính; không thuộc PRIORITY để bước nghiệp vụ (và tuyến sau) không bao giờ
# gán. Xét sau mọi nhãn trong PRIORITY.
IDENTITY_ONLY: tuple[Intent, ...] = (Intent.CANNOT_PROVIDE,)

_DIRECTION_ONLY: dict[Intent, Direction] = {Intent.CONFIRM: "outbound", Intent.BOOK: "inbound"}
# Nhãn hành động: cụm phủ định đứng trước làm mất nhãn
_NEGATABLE = frozenset(
    {Intent.REQUEST_HUMAN, Intent.RESCHEDULE, Intent.CANCEL, Intent.BOOK, Intent.CONFIRM}
)

_KEYWORDS: dict[Intent, list[str]] = {
    Intent.REQUEST_HUMAN: [
        "nhân viên",
        "gặp nhân viên",
        "gặp người",
        "người thật",
        "tổng đài viên",
        "chuyển máy",
        "gặp tư vấn viên",
        "nói chuyện với người",
        "gặp lễ tân",
        "gặp người trực",
    ],
    Intent.NOT_PATIENT: [
        "đi vắng",
        "không có nhà",
        "không ở nhà",
        "nhầm số",
        "gọi nhầm",
        "người nhà bệnh nhân",
    ],
    Intent.OUT_OF_SCOPE: [
        "bảo hiểm",
        "thanh toán",
        "hóa đơn",
        "viện phí",
        "hoàn tiền",
        "chuyển tuyến",
        "chuyển viện",
        "giấy chuyển",
        "đơn thuốc",
        "kê đơn",
        "kết quả xét nghiệm",
        "trả kết quả",
    ],
    Intent.RESCHEDULE: [
        "đổi lịch",
        "đổi sang",
        "đổi qua",
        "đổi giờ",
        "đổi ngày",
        "đổi hôm",
        "dời lịch",
        "dời sang",
        "dời qua",
        "dời",
        "lùi lịch",
        "lùi sang",
        "hoãn sang",
        "chuyển sang",
        "chuyển lịch",
        "đặt lại lịch",
        "hẹn lại",
        "lịch khác",
        "khung khác",
        "giờ khác",
        "hôm khác",
        "ngày khác",
        "đổi lại",
    ],
    Intent.CANCEL: [
        "hủy",
        "không đi được",
        "không đến được",
        "đến không được",
        "đi không được",
        "không khám nữa",
        "không đi khám được",
        "bỏ lịch",
        "không đi nữa",
        "không đến nữa",
        "sẽ không đến",
        "sẽ không đi",
        "không cần khám nữa",
    ],
    Intent.BOOK: [
        "đặt lịch",
        "đặt hẹn",
        "đăng ký khám",
        "muốn khám",
        "hẹn khám",
        "lấy lịch",
        "đặt khám",
    ],
    Intent.CONFIRM: [
        "sẽ đến",
        "sẽ đi",
        "tôi đến",
        "đến được",
        "đi được",
        "có đến",
        "có đi",
        "vẫn đến",
        "vẫn đi",
        "giữ lịch",
        "giữ nguyên",
        "giữ nguyên lịch",
        "vẫn giữ lịch",
        "đúng lịch",
        "xác nhận",
        # Trả lời "đổi hay hủy" bằng cách giữ lịch (T-04 §8)
        "không đổi không hủy",
        "không đổi cũng không hủy",
        "không đổi gì",
        "không hủy gì",
    ],
    Intent.REPEAT_REQUEST: [
        "gì cơ",
        "sao cơ",
        "nói lại",
        "nhắc lại",
        "lặp lại",
        "nghe không rõ",
        "không nghe rõ",
        "chưa nghe rõ",
        "nghe chưa rõ",
        "nói chậm",
        "nghe không kịp",
    ],
    # Cố ý không có "không biết" / "không rõ" đứng một mình: "không biết ai gọi", "không rõ" (nghe không rõ)
    Intent.CANNOT_PROVIDE: [
        "không nhớ",
        "chẳng nhớ",
        "quên mất",
        "quên rồi",
        "không muốn nói",
        "không muốn cung cấp",
        "không tiện nói",
        "không tiện cung cấp",
        "không cung cấp",
        "không nói được",
        "không biết ngày sinh",
        "không biết năm sinh",
    ],
}
_UNACCENTED_EXCLUDE: dict[Intent, list[str]] = {
    Intent.RESCHEDULE: ["dời", "đổi lại"],  # "doi" = đợi / đói / đội; "doi lai" = đợi lại
    # "toi den" = tối đến; "dung lich" = dùng lịch; "khong doi gi" = không đợi gì
    Intent.CONFIRM: ["tôi đến", "đúng lịch", "không đổi gì"],
    Intent.CANNOT_PROVIDE: ["quên mất", "quên rồi"],  # "quen mat" = quen mặt; "quen roi" = quen rồi
}
# Nhãn chỉ-một-hướng vẫn nhận ở hướng kia với cụm hẹp, để Dialogue chuyển máy vì ngoài kịch bản
# (§1.1.5) thay vì hỏi lại. Inbound "xác nhận lịch khám" nói về lịch có sẵn; "tôi đến được" thì không —
# inbound "sáng mai tôi đến được không" là nhu cầu đặt lịch (T-04).
_CROSS_DIRECTION_KEYWORDS: dict[tuple[Intent, Direction], list[str]] = {
    (Intent.CONFIRM, "inbound"): [
        "xác nhận lịch",
        "xác nhận lịch hẹn",
        "xác nhận lịch khám",
        "xác nhận cuộc hẹn",
    ],
}
_COMPILED = {
    intent: compile_phrases(words, _UNACCENTED_EXCLUDE.get(intent, ()))
    for intent, words in _KEYWORDS.items()
}

# "tôi là vợ anh ấy", "em là con của bà ấy", "anh ấy đi làm rồi"
_RELATIVE = (
    r"(?:vợ|chồng|con|con trai|con gái|mẹ|bố|cha|ba|má|anh|chị|em|cháu|người nhà|bạn|hàng xóm)"
)
_THIRD_PERSON = r"(?:anh|chị|ông|bà|cô|chú|bác|em|cháu|bạn) ấy"
_NOT_PATIENT_SOURCES = [
    rf"(?<!\w)(?:tôi|em|mình|con|cháu) là {_RELATIVE}(?: của)? (?:{_THIRD_PERSON}|bệnh nhân|người đó)(?!\w)",
    rf"(?<!\w){_THIRD_PERSON} (?:đi làm|ra ngoài|không nghe máy|đang bận|không có ở đây|đi công tác)(?!\w)",
]
_CROSS_DIRECTION = {key: compile_phrases(words) for key, words in _CROSS_DIRECTION_KEYWORDS.items()}
_NOT_PATIENT_PATTERNS = [re.compile(source) for source in _NOT_PATIENT_SOURCES]
_NOT_PATIENT_PATTERNS_UNACCENTED = [
    re.compile(strip_diacritics(source)) for source in _NOT_PATIENT_SOURCES
]
# Chỉ tính là xin nhắc lại khi cả câu chỉ có vậy: "hả?", "gì?", "cái gì?"
# Không có "alo": "alo" là chưa hiểu (tính §1.1.5), không phải xin nhắc lại.
_REPEAT_WHOLE_UTTERANCE = frozenset({"hả", "gì", "cái gì", "sao", "gì ạ", "sao ạ", "hả em"})
_REPEAT_WHOLE_UTTERANCE_UNACCENTED = frozenset(strip_diacritics(u) for u in _REPEAT_WHOLE_UTTERANCE)


def extract_intent(
    transcript: str,
    direction: Direction,
    allowed: Optional[Iterable[Intent]] = None,
) -> Field[Intent]:
    text = clean(transcript)
    unaccented = is_unaccented(text)
    provenance = Provenance.NORMALIZED if unaccented else Provenance.EXACT
    allowed_set = frozenset(allowed) if allowed is not None else frozenset(PRIORITY)
    for intent in (*PRIORITY, *IDENTITY_ONLY):
        if intent not in allowed_set:
            continue
        if allowed_in_direction(intent, direction):
            span = _match(intent, text, unaccented)
        elif (intent, direction) in _CROSS_DIRECTION:
            found = find_phrase(
                text,
                _CROSS_DIRECTION[(intent, direction)],
                allow_negated=False,
                unaccented=unaccented,
            )
            span = found.group(0) if found else None
        else:
            continue
        if span is not None:
            return Field(intent, provenance, span=span)
    return Field.nothing(Intent.NONE)


def allowed_in_direction(intent: Intent, direction: Direction) -> bool:
    return _DIRECTION_ONLY.get(intent, direction) == direction


def _match(intent: Intent, text: str, unaccented: bool) -> Optional[str]:
    if intent is Intent.NOT_PATIENT:
        for pattern in _NOT_PATIENT_PATTERNS_UNACCENTED if unaccented else _NOT_PATIENT_PATTERNS:
            found = pattern.search(text)
            if found:
                return found.group(0)
    whole = _REPEAT_WHOLE_UTTERANCE_UNACCENTED if unaccented else _REPEAT_WHOLE_UTTERANCE
    if intent is Intent.REPEAT_REQUEST and text in whole:
        return text
    found = find_phrase(
        text, _COMPILED[intent], allow_negated=intent not in _NEGATABLE, unaccented=unaccented
    )
    return found.group(0) if found else None
