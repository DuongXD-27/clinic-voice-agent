"""Intent — thiết kế v1.1 §5.4 (tầng luật viết tay).

Ưu tiên khi một câu khớp nhiều nhãn:
    REQUEST_HUMAN > NOT_PATIENT > OUT_OF_SCOPE (chủ đề) > RESCHEDULE > CANCEL > BOOK
    > OUT_OF_SCOPE (yêu cầu) > CONFIRM > REPEAT_REQUEST

- "Không đến được, đổi sang chiều được không" -> RESCHEDULE (có phương án thay thế).
- Phủ định đứng trước từ khoá hành động bị loại: "không hủy", "đừng đổi", "chưa muốn đặt lịch".
  Không áp dụng cho chủ đề OUT_OF_SCOPE ("không có bảo hiểm thì sao" vẫn là câu hỏi bảo hiểm), nhưng áp
  dụng cho yêu cầu OUT_OF_SCOPE ("không đến trễ đâu", "không cần gọi lại" không phải yêu cầu).
- OUT_OF_SCOPE gồm chủ đề ngoài phạm vi (§1.2.3, địa chỉ / đường đi) và yêu cầu ngoài kịch bản mà bot
  hiểu được: người khác đi khám thay, đến muộn, xin gọi lại. Yêu cầu xếp sau đổi / hủy / đặt — câu có
  nhu cầu trong phạm vi thì làm nhu cầu đó ("tôi sợ đến trễ, dời sang 10 giờ" -> RESCHEDULE) — nhưng
  trước CONFIRM ("vợ tôi sẽ đến thay" không phải đồng ý). Cụm gọi lại ngắn xét ở bước nghiệp vụ;
  yêu cầu trực tiếp "gọi lại cho tôi" / "giúp tôi" áp dụng cả trước xác minh (§1.1.5).
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
    # Chỉ khung yêu cầu rõ ràng: "nhân viên" đứng trơ trong câu kể ("nhân viên đã hẹn tôi đến hôm
    # đó", "tôi không muốn gặp bất kỳ nhân viên nào") không phải xin gặp người. Cả câu chỉ có "nhân
    # viên" vẫn là yêu cầu (xem `_match`).
    Intent.REQUEST_HUMAN: [
        "gặp nhân viên",
        "chuyển nhân viên",
        "chuyển sang nhân viên",
        "chuyển cho nhân viên",
        "chuyển qua nhân viên",
        "chuyển tôi sang nhân viên",
        "chuyển tôi cho nhân viên",
        "nói chuyện với nhân viên",
        "nói với nhân viên",
        "kết nối nhân viên",
        "kết nối với nhân viên",
        "nối máy",
        "cần nhân viên",
        "gọi nhân viên",
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
        # Câu hỏi chi phí là ngoài phạm vi; không bắt riêng "phí" vì "đắt quá" có thể
        # là lý do hủy COST, vẫn thuộc nghiệp vụ.
        "mất phí không",
        "có phí không",
        "hết bao nhiêu tiền",
        "chi phí bao nhiêu",
        "giá khám bao nhiêu",
        # Phủ nhận lịch đang được đọc: không đoán người nào đã đặt hoặc tự xác nhận.
        "lịch này tôi có đặt đâu",
        "tôi có đặt lịch nào đâu",
        "tôi không đặt lịch này",
        "tôi không nhớ là có đặt lịch này",
        "ai đặt lịch này cho tôi",
        "tôi có hẹn gì bên mình đâu",
        "hoàn tiền",
        "chuyển tuyến",
        "chuyển viện",
        "giấy chuyển",
        "đơn thuốc",
        "kê đơn",
        "kết quả xét nghiệm",
        "trả kết quả",
        # Địa chỉ / đường đi: chỉ cụm dạng hỏi / xin. Danh từ trơ "địa chỉ bệnh viện" không đủ: "tôi
        # biết địa chỉ bệnh viện rồi, tôi sẽ đến" là câu kể — câu không khớp cụm nào thì để model đọc.
        "địa chỉ ở đâu",
        "địa chỉ là gì",
        "địa chỉ cụ thể",
        "địa chỉ thế nào",
        "địa chỉ chỗ nào",
        "xin địa chỉ",
        "cho tôi địa chỉ",
        "gửi địa chỉ",
        "hỏi địa chỉ",
        "phòng khám ở đâu",
        "cơ sở ở đâu",
        "bệnh viện ở đâu",
        "chỉ đường",
        "đi đường nào",
        "gửi xe ở đâu",
        "chỗ gửi xe",
        "bãi gửi xe",
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
        "không muốn khai",
        "không muốn cung cấp",
        "không khai",
        "không nói tên",
        "không nói đâu",
        "không cho biết tên",
        "không tiết lộ tên",
        "không tiện nói",
        "không tiện cung cấp",
        "không cung cấp",
        "không nói được",
        "không biết ngày sinh",
        "không biết năm sinh",
    ],
}
# Yêu cầu ngoài kịch bản (§1.1.5): bot hiểu được nhưng không có luồng xử lý. Phủ định đứng trước làm
# mất nhãn ("không đến trễ đâu").
_OUT_OF_SCOPE_REQUESTS = [
    "để lại tin nhắn giúp tôi",
    "nhắn tin giúp tôi",
    "gửi tin nhắn cho tôi",
    "nhắn tin lịch khám",
    "gọi lại sau nhé",
    "gọi lại sau giúp tôi",
    "gọi lại cho tôi",
    # người khác đi khám thay người bệnh
    "đến thay",
    "đi thay",
    "khám thay",
    "đi khám thay",
    "đến khám thay",
    "khám hộ",
    "đi khám hộ",
    # đến muộn so với lịch
    "đến muộn",
    "đến trễ",
    "đi muộn",
    "đi trễ",
    "tới muộn",
    "tới trễ",
]
# Cụm gọi lại ngắn chỉ ở bước nghiệp vụ; lời yêu cầu trực tiếp "gọi lại cho tôi" / "giúp tôi"
# ở _OUT_OF_SCOPE_REQUESTS áp dụng cả trước xác minh. "rồi gọi lại" không nằm ở đây.
_CALLBACK_REQUESTS = [
    "gọi lại sau",
    "gọi lại cho tôi",
    "gọi lại giúp",
    "gọi lại lúc khác",
    "gọi lúc khác",
    "lát gọi lại",
    "lát nữa gọi lại",
]
# "den thay" = đến thấy; "di thay" = đi thấy; "kham thay" = khám thấy; "di muon" = đi mượn;
# "toi muon" = TÔI MUỐN; "toi tre" = tôi trẻ
_REQUESTS_UNACCENTED_EXCLUDE = [
    "đến thay",
    "đi thay",
    "khám thay",
    "đi khám thay",
    "đến khám thay",
    "đi muộn",
    "tới muộn",
    "tới trễ",
]
# "thay đổi / thay băng / thay thuốc / thay đồ" không phải người khác đi thay; "không ai đi thay" là phủ
# định mà `is_negated` không thấy (có "ai" chen giữa). Chỉ cần bản có dấu: bản không dấu của các cụm "thay"
# đã bị loại ở trên.
_NOT_A_REQUEST = re.compile(
    r"(?<!\w)(?:thay (?:đổi|băng|thuốc|đồ)"
    r"|(?:không|chẳng)(?: có)? ai (?:đi|đến|tới)(?: khám)? thay)(?!\w)"
)
_UNACCENTED_EXCLUDE: dict[Intent, list[str]] = {
    Intent.RESCHEDULE: ["dời", "đổi lại"],  # "doi" = đợi / đói / đội; "doi lai" = đợi lại
    # "toi den" = tối đến; "dung lich" = dùng lịch; "khong doi gi" = không đợi gì
    Intent.CONFIRM: ["tôi đến", "đúng lịch", "không đổi gì"],
    Intent.CANNOT_PROVIDE: ["quên mất", "quên rồi"],  # "quen mat" = quen mặt; "quen roi" = quen rồi
    Intent.OUT_OF_SCOPE: ["chỉ đường"],  # "chi duong" = chị Dương
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
_COMPILED_REQUESTS = compile_phrases(_OUT_OF_SCOPE_REQUESTS, _REQUESTS_UNACCENTED_EXCLUDE)
_COMPILED_CALLBACK = compile_phrases(_CALLBACK_REQUESTS)

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
    *,
    business_step: bool = True,
) -> Field[Intent]:
    """`business_step=False`: bước danh tính, không xét cụm xin gọi lại."""
    text = clean(transcript)
    unaccented = is_unaccented(text)
    provenance = Provenance.NORMALIZED if unaccented else Provenance.EXACT
    allowed_set = frozenset(allowed) if allowed is not None else frozenset(PRIORITY)
    for intent in (*PRIORITY, *IDENTITY_ONLY):
        if intent is Intent.CONFIRM and Intent.OUT_OF_SCOPE in allowed_set:
            # Yêu cầu ngoài kịch bản: sau đổi / hủy / đặt, trước CONFIRM (xem docstring)
            span = _match_out_of_scope_request(text, unaccented, business_step)
            if span is not None:
                return Field(Intent.OUT_OF_SCOPE, provenance, span=span)
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
    if intent is Intent.REQUEST_HUMAN and _without_particles(text, unaccented) in _HUMAN_ALONE:
        return text
    whole = _REPEAT_WHOLE_UTTERANCE_UNACCENTED if unaccented else _REPEAT_WHOLE_UTTERANCE
    if intent is Intent.REPEAT_REQUEST and text in whole:
        return text
    found = find_phrase(
        text, _COMPILED[intent], allow_negated=intent not in _NEGATABLE, unaccented=unaccented
    )
    if found and intent is Intent.NOT_PATIENT and _first_person_before(text, found, unaccented):
        # "Tôi đi vắng nên muốn đổi lịch": chính người bệnh nói mình vắng, không phải người khác nghe
        return None
    return found.group(0) if found else None


# Cả câu chỉ là "nhân viên" (kèm tiểu từ / xưng hô): vẫn là xin gặp người
_HUMAN_ALONE = frozenset({clean("nhân viên"), "nhan vien"})
_PARTICLES = frozenset(
    clean(w) for w in ["ạ", "à", "đi", "nhé", "nha", "ơi", "em", "cho", "tôi", "với", "dạ", "vâng"]
)
_PARTICLES_UNACCENTED = frozenset(strip_diacritics(w) for w in _PARTICLES)
_FIRST_PERSON = frozenset({"tôi", "mình", "tớ", "em"})
_FIRST_PERSON_UNACCENTED = frozenset({"toi", "minh", "to", "em"})


def _without_particles(text: str, unaccented: bool) -> str:
    particles = _PARTICLES_UNACCENTED if unaccented else _PARTICLES
    return " ".join(w for w in text.split() if w not in particles)


def _first_person_before(text: str, found: re.Match[str], unaccented: bool) -> bool:
    """Chủ ngữ ngôi thứ nhất trong ba từ trước cụm vắng mặt ("tôi đi vắng", "tôi hiện không ở nhà")."""
    pronouns = _FIRST_PERSON_UNACCENTED if unaccented else _FIRST_PERSON
    return bool(pronouns.intersection(text[: found.start()].split()[-3:]))


def _match_out_of_scope_request(text: str, unaccented: bool, business_step: bool) -> Optional[str]:
    phrase_sets = (
        (_COMPILED_REQUESTS, _COMPILED_CALLBACK) if business_step else (_COMPILED_REQUESTS,)
    )
    # Dấu ";" giữ ranh giới từ: cụm bị xoá không làm hai từ hai bên ghép thành cụm mới
    text = _NOT_A_REQUEST.sub(" ; ", text)
    for phrases in phrase_sets:
        found = find_phrase(text, phrases, allow_negated=False, unaccented=unaccented)
        if found:
            return found.group(0)
    return None
