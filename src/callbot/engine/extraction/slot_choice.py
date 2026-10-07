"""Chọn slot — thiết kế v1.1 §5.7.

Lời người gọi chỉ được biến thành TIÊU CHÍ LỌC trên tập slot `GET /slots` của chính cuộc gọi này.
Không bao giờ dựng mốc thời gian mới từ lời nói, nên SF-02 không xảy ra được về mặt cấu trúc.

- MATCH(slot_id)      đúng 1 slot thoả mọi tiêu chí
- AMBIGUOUS(slot_ids) nhiều slot -> bot đọc tối đa 2 slot trong số đó, hỏi lại (không tự chọn slot đầu)
- NO_MATCH            không slot nào, hoặc không rút ra được tiêu chí nào
- MORE                không có tiêu chí, xin nghe khung khác ("khung khác", "còn khung nào")
- ANY                 không có tiêu chí, khung nào cũng được ("nào cũng được", "sớm nhất", "tùy em")

Ngày tương đối ("mai", "thứ năm tuần sau") tính theo ngày cuộc gọi, múi giờ +07:00.

Transcript không dấu: khôi phục dấu cho bảng từ ngày giờ đóng trước khi parse. "sang"/"toi" chỉ thành
"sáng"/"tối" khi đứng sau "giờ"/"rưỡi"/"buổi" — "doi sang chieu" là "đổi sang chiều", "toi muon" là "tôi muốn".
Khôi phục sai chỉ làm lệch tiêu chí lọc (NO_MATCH / AMBIGUOUS); slot vẫn chỉ lấy từ GET /slots và vẫn phải đọc lại.

PRD R-44 — tự sửa trong câu: "9 giờ, à không, 10 giờ", "thứ Sáu ngày 15… à không, 14" dùng giá trị nói
SAU CÙNG. Tiêu chí của phần sửa thay tiêu chí cùng loại của phần trước; tiêu chí phần sau không nhắc lại
thì giữ ("thứ Sáu" vẫn còn khi chỉ sửa ngày). Số trần ở phần sửa ("à không, 14") mượn đơn vị của số bị sửa
("ngày 15" -> "ngày 14", "9 giờ" -> "10 giờ"). "à không" ở đây là lời sửa, không phải lời từ chối (R-41).
"""

import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

from callbot.engine.extraction.identity import CORRECTIONS
from callbot.engine.extraction.schema import (
    DayPeriod,
    Field,
    Provenance,
    Relative,
    SlotChoice,
    SlotCriteria,
    to_local,
)
from callbot.engine.extraction.spoken_numbers import (
    is_number_token,
    parse_number,
    restore_number_words,
)
from callbot.engine.extraction.text import (
    PhraseSet,
    clean,
    compile_phrases,
    drop_leading_words,
    find_phrase,
    is_unaccented,
    keep_leading_words,
    normalize,
    strip_diacritics,
)

_PERIOD_HOURS: dict[DayPeriod, range] = {
    "MORNING": range(0, 12),
    "NOON": range(11, 14),
    "AFTERNOON": range(12, 18),
    "EVENING": range(18, 24),
}
_PERIOD_WORDS: dict[str, DayPeriod] = {
    "sáng": "MORNING",
    "trưa": "NOON",
    "chiều": "AFTERNOON",
    "tối": "EVENING",
}

_ORDINAL_WORDS = {"nhất": 1, "một": 1, "hai": 2, "ba": 3, "tư": 4, "bốn": 4, "năm": 5}
_ORDINAL = re.compile(
    r"(?<!\w)(?:khung|cái|lựa chọn|phương án|slot|số)\s+(?:thứ\s+|số\s+)?(nhất|một|hai|ba|tư|bốn|năm|[1-9])"
    r"(?!\w)(?!\s+(?:giờ|rưỡi|kém|h)(?!\w))"
)
# Trang đọc theo thứ tự thời gian: khung sớm nhất / gần nhất là khung 1 (T-10 §3.8.1)
_FIRST = re.compile(
    r"(?<!\w)(?:đầu tiên|cái đầu|khung đầu|slot đầu|cái gần nhất|khung gần nhất|cái sớm nhất"
    r"|khung sớm nhất|cái trước|khung trước)(?!\w)"
)
# "cái sau", "cái kia", "cái còn lại": khung còn lại của trang 2 khung. "khung sau" là xin nghe tiếp
_LAST = re.compile(
    r"(?<!\w)(?:cái cuối|khung cuối|slot cuối|sau cùng|cuối cùng|cái sau|cái kia|cái còn lại"
    r"|giờ còn lại|khung còn lại)(?!\w)"
)
# R008: "chọn giờ thứ 2" là thứ tự; "10 giờ thứ Hai" (có số trước "giờ") là giờ + thứ
_HOUR_ORDINAL = re.compile(r"(?<!\w)giờ\s+thứ\s+(nhất|một|hai|ba|[1-3])(?!\w)")

_RELATIVE_DAYS = [
    (re.compile(r"(?<!\w)hôm nay(?!\w)"), 0),
    (re.compile(r"(?<!\w)hôm qua(?!\w)"), -1),
    # "mốt" đứng riêng chỉ nhận bản có dấu: "mot" không dấu là "một"
    (re.compile(r"(?<!\w)(?:ngày kia|ngày mốt|ngày mai kia|mốt)(?!\w)"), 2),
    (re.compile(r"(?<!\w)(?:ngày mai|mai)(?!\w)"), 1),
]
# R-30: xét trước `_WEEK`, vì "cuối tuần này" / "tuần sau nữa" chứa "tuần này" / "tuần sau"
_WEEK_AFTER_NEXT = re.compile(r"(?<!\w)tuần (?:sau|tới) nữa(?!\w)")
_WEEK_PART = re.compile(r"(?<!\w)(đầu|cuối) tuần(?: (sau|tới|này))?(?!\w)")
_WEEK = re.compile(r"(?<!\w)tuần (sau|tới|này)(?!\w)")
# Quá rộng để tra (R-30): hỏi lại ngày cụ thể. "mùng 5 tháng sau" có ngày -> quy về tháng sau
_MONTH_RELATIVE = re.compile(r"(?<!\w)tháng (sau|tới|này)(?!\w)")
_MONTH_PART = re.compile(r"(?<!\w)(?:đầu|giữa|cuối) tháng(?!\w)")
# Ngày đã qua trong khoảng này là "đã qua" (hỏi lại); xa hơn thì hiểu là năm sau
PAST_DATE_WINDOW = timedelta(days=180)
_WEEKDAY = re.compile(r"(?<!\w)(?:thứ\s+(hai|ba|tư|năm|sáu|bảy|[2-7])|(chủ nhật))(?!\w)")
_WEEKDAY_INDEX = {"hai": 0, "ba": 1, "tư": 2, "năm": 3, "sáu": 4, "bảy": 5}

# Chuẩn hoá dạng số trước khi bỏ dấu câu: "14h30", "14:30" -> "14 giờ 30"; "20/10" -> "ngày 20 tháng 10"
_NUMERIC_TIME = re.compile(r"(?<!\d)(\d{1,2})\s*(?:h|:|g)\s*(\d{2})?(?!\w)")
_NUMERIC_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\s*/)(?!\d)")

_UNACCENTED_PHRASES = {
    "hom nay": "hôm nay",
    "hom qua": "hôm qua",
    "tuan sau nua": "tuần sau nữa",
    "tuan toi nua": "tuần tới nữa",
    "cuoi tuan": "cuối tuần",
    "dau tuan": "đầu tuần",
    "thang sau": "tháng sau",
    "thang toi": "tháng tới",
    "thang nay": "tháng này",
    "dau thang": "đầu tháng",
    "giua thang": "giữa tháng",
    "cuoi thang": "cuối tháng",
    "ngay mai kia": "ngày mai kia",
    "ngay mai": "ngày mai",
    "ngay kia": "ngày kia",
    "ngay mot": "ngày mốt",
    "tuan sau": "tuần sau",
    "tuan toi": "tuần tới",
    "tuan nay": "tuần này",
    "chu nhat": "chủ nhật",
    "cai dau": "cái đầu",
    "dau tien": "đầu tiên",
    "khung dau": "khung đầu",
    "slot dau": "slot đầu",
    "cai cuoi": "cái cuối",
    "cai gan nhat": "cái gần nhất",
    "cai som nhat": "cái sớm nhất",
    "cai truoc": "cái trước",
    "cai kia": "cái kia",
    "cai con lai": "cái còn lại",
    "cai sau": "cái sau",
    "gio con lai": "giờ còn lại",
    "khung con lai": "khung còn lại",
    "khung cuoi": "khung cuối",
    "slot cuoi": "slot cuối",
    "sau cung": "sau cùng",
    "cuoi cung": "cuối cùng",
    "lua chon": "lựa chọn",
    "phuong an": "phương án",
    "thu hai": "thứ hai",
    "thu ba": "thứ ba",
    "thu tu": "thứ tư",
    "thu nam": "thứ năm",
    "thu sau": "thứ sáu",
    "thu bay": "thứ bảy",
    "cai thu": "cái thứ",
    "khung thu": "khung thứ",
    "sang mai": "sáng mai",
    "sang nay": "sáng nay",
    "toi mai": "tối mai",
    "toi nay": "tối nay",
}
_UNACCENTED_PHRASE_RE = [
    (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)"), v)
    for k, v in sorted(_UNACCENTED_PHRASES.items(), key=lambda kv: -len(kv[0]))
]
_UNACCENTED_WEEKDAY_DIGIT = re.compile(r"(?<!\w)thu (?=[2-7](?!\w))")
_UNACCENTED_WORDS = {
    "gio": "giờ",
    "ruoi": "rưỡi",
    "kem": "kém",
    "phut": "phút",
    "chieu": "chiều",
    "trua": "trưa",
    "buoi": "buổi",
    "mung": "mùng",
    "mong": "mồng",
    "ngay": "ngày",
    "thang": "tháng",
    "lam": "lăm",
    "nhat": "nhất",
}
_PERIOD_AFTER = frozenset({"giờ", "rưỡi", "phút", "buổi"})

# Xin nghe khung khác mà không nêu tiêu chí mới (T-10). Câu có tiêu chí ("khung khác, buổi sáng ấy")
# thì tiêu chí thắng. "sớm hơn / muộn hơn" chỉ là xin khung khác, không dựng mốc giờ tương đối.
_MORE = compile_phrases(
    [
        "khung khác",
        "giờ khác",
        "cái khác",
        "lịch khác",
        "ngày khác",
        "hôm khác",
        "buổi khác",
        "còn khung nào",
        "còn giờ nào",
        "khung nào khác",
        "giờ nào khác",
        "nghe tiếp",
        "đọc tiếp",
        "sớm hơn",
        "muộn hơn",
        "trễ hơn",
        "còn lại",
        "còn gì nữa",
        "còn gì khác",
        "còn nữa không",
        "còn cái nào",
        "còn khung không",
        "còn giờ không",
        "xem nốt",
        "nghe nốt",
        "đọc nốt",
        "khung tiếp",
        "khung sau",
    ]
)
# Khung nào cũng được, không nêu tiêu chí (T-10 D-1). "Sáng nào cũng được" có tiêu chí buổi -> tiêu chí thắng
_ANY = compile_phrases(
    [
        "nào cũng được",
        "lúc nào cũng được",
        "khi nào cũng được",
        "hôm nào cũng được",
        "ngày nào cũng được",
        "giờ nào cũng được",
        "khung nào cũng được",
        "tùy em",
        "tuỳ em",
        "em chọn giúp",
        "sớm nhất",
        "sớm nhất có thể",
        "càng sớm càng tốt",
    ]
)
# Số lượng khung ("2 khung cuối", "mấy khung còn lại", "4 khung khác"): xin nghe tiếp, không phải chọn
# khung cuối của trang, không phải giờ hay thứ. Khớp trên bản bỏ dấu (độ dài giữ nguyên) để cắt đúng chỗ.
_SLOT_COUNT = re.compile(
    r"(?<!\w)(\d+|mot|hai|ba|bon|nam|sau|may|cac|nhung) (?:khung|cai|slot)(?: gio)? "
    r"(?:cuoi|con lai|nua|tiep|sau|khac|kia)(?!\w)"
)
_COUNT_WORDS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6}


# Hỏi lại câu bot vừa đọc ("sao lại là thứ Sáu", "thứ Sáu à"): không phải chọn khung (T-10 §3.8.1)
_ASKS_BACK = compile_phrases(
    ["sao lại", "tại sao", "vì sao", "thật à", "thật hả", "thế à", "vậy à"]
)
_ASKS_BACK_FINALS = frozenset({"à", "hả", "hở", "a", "ha", "ho"})


# So với lịch đang đổi: Dialogue gắn mốc là giờ lịch hẹn (`anchor_relative`)
_RELATIVE: dict[Relative, PhraseSet] = {
    "EARLIER": compile_phrases(["sớm hơn một chút", "sớm hơn chút", "sớm hơn"]),
    "LATER": compile_phrases(["muộn hơn một chút", "muộn hơn chút", "muộn hơn", "trễ hơn"]),
}

# Lời xin một thời điểm: "… có được không", "cho tôi …", "tôi muốn …", "chiều thứ Sáu tôi rảnh". Không có
# lời xin thì giờ trong câu có thể chỉ là hỏi lại / thắc mắc ("9 giờ hả em?", "tôi tưởng hẹn 9 giờ").
_TIME_REQUEST = compile_phrases(
    [
        "được không",
        "được chứ",
        "có được",
        "cho tôi",
        "cho em",
        "cho mình",
        "cho chị",
        "cho anh",
        "lấy",
        "muốn",
        "rảnh",
        "tiện",
        "đi được",
        "đến được",
        "khám được",
    ]
)
# Không dấu: "a" / "ha" trùng "ạ" / "hạ" -> chỉ tin bản có dấu của "à", "hả"
_TIME_DOUBT = compile_phrases(
    ["tưởng", "không phải", "hả", "à", "sao lại", "nhầm"], unaccented_exclude=["hả", "à"]
)
# Hỏi còn chỗ: "có 4 giờ chiều ngày 16 không em", "còn khung sáng thứ Sáu không ạ"
_AVAILABILITY = re.compile(r"(?:^| )(?:có|còn) (?:\S+ ){1,8}?không(?: (?:em|ạ|nhỉ|nhé|vậy|thế))?$")
_AVAILABILITY_UNACCENTED = re.compile(
    r"(?:^| )(?:co|con) (?:\S+ ){1,8}?khong(?: (?:em|a|nhi|nhe|vay|the))?$"
)
# Câu cầu khiến kết bằng "đi": "5 giờ chiều ngày 14 đi em". Từ ngay trước "đi" là chủ ngữ / trạng từ
# ("tôi đi", "vẫn đi") thì là câu kể việc đi khám. "nhé" không tính: "vâng, 3 giờ chiều nhé" là hỏi lại
# giờ hẹn, không phải xin giờ khác.
_IMPERATIVE_TAIL = re.compile(r"(?:^| )(\S+) đi(?: (?:em|ạ|nhé|nha|nhá))*$")
_IMPERATIVE_TAIL_UNACCENTED = re.compile(r"(?:^| )(\S+) di(?: (?:em|a|nhe|nha))*$")
_NOT_IMPERATIVE_HEAD = frozenset(
    ["tôi", "em", "mình", "anh", "chị", "cô", "chú", "bác", "cháu", "con", "vẫn", "sẽ", "cũng", "được"]
)  # fmt: skip
_NOT_IMPERATIVE_HEAD_UNACCENTED = frozenset(strip_diacritics(w) for w in _NOT_IMPERATIVE_HEAD)


# Từ được phép còn lại trong câu xin giờ, sau khi bỏ cụm thời gian (`strip_slot_phrases`): lời xin, khung
# hỏi chỗ "có / còn … không", động từ dời, mức "sớm / muộn hơn", tiểu từ và xưng hô. Còn từ nào khác ("hỏi",
# "nhịn ăn", "mang theo", "gọi lại") thì câu nói việc khác, không phải xin giờ (§1.1.5: không đoán). Thêm một
# từ ở đây là nới cửa vào luồng đổi lịch: mỗi từ mới cần một câu âm tính trong test.
_TIME_REQUEST_WORDS = [
    # lời xin
    "được", "không", "chứ", "cho", "xin", "lấy", "muốn", "rảnh", "tiện", "đi", "đến", "khám", "thử",
    "giúp", "hộ", "cũng", "thì", "vậy", "thế",
    # hỏi chỗ
    "có", "còn", "nào", "khung", "chỗ", "trống", "lịch",
    # dời lịch
    "đổi", "dời", "chuyển", "lùi", "hoãn", "sang", "qua", "để",
    # mốc giờ
    "khoảng", "tầm", "sớm", "muộn", "trễ", "hơn", "chút", "một",
    # tiểu từ, xưng hô
    "ạ", "nhé", "nha", "nhá", "luôn", "đó", "ơi", "tôi", "em", "anh", "chị", "mình", "tớ", "cháu", "con",
    "bác", "cô", "chú", "ông", "bà", "chúng",
]  # fmt: skip
_TIME_REQUEST_ALLOWED = frozenset(clean(w) for w in _TIME_REQUEST_WORDS) | frozenset(
    strip_diacritics(clean(w)) for w in _TIME_REQUEST_WORDS
)


def requests_time(transcript: str) -> bool:
    """Câu xin một thời điểm (để đổi lịch), không phải hỏi lại / thắc mắc về giờ.

    Cần lời xin, và CẢ CÂU chỉ gồm cụm thời gian, lời xin và từ đệm (danh sách cho phép): "ngày mai tôi có
    phải nhịn ăn không" có "có … không" nhưng còn "phải nhịn ăn" -> không phải xin giờ.

    Câu gốc không dấu: `_prepare` chỉ khôi phục dấu cho từ chỉ giờ / ngày, nên câu thành nửa có dấu nửa
    không ("cho toi 9 giờ sáng mai duoc không"). Lời xin khớp trên MỘT dạng là bản bỏ dấu toàn bộ; cụm thời
    gian vẫn bỏ trên bản `_prepare` (có dấu), nơi `strip_slot_phrases` nhận ra chúng.
    """
    prepared = _prepare(transcript)
    unaccented = is_unaccented(clean(normalize(transcript)))
    text = strip_diacritics(prepared) if unaccented else prepared
    if find_phrase(text, _TIME_DOUBT, unaccented=unaccented) is not None:
        return False
    tail = (_IMPERATIVE_TAIL_UNACCENTED if unaccented else _IMPERATIVE_TAIL).search(text)
    heads = _NOT_IMPERATIVE_HEAD_UNACCENTED if unaccented else _NOT_IMPERATIVE_HEAD
    availability = _AVAILABILITY_UNACCENTED if unaccented else _AVAILABILITY
    asked = (
        find_phrase(text, _TIME_REQUEST, unaccented=unaccented) is not None
        or availability.search(text) is not None
        or (tail is not None and tail.group(1) not in heads)
    )
    rest = strip_slot_phrases(prepared).split()
    if unaccented:
        rest = [strip_diacritics(w) for w in rest]
    return asked and all(w in _TIME_REQUEST_ALLOWED for w in rest)


# Cụm thời gian / thứ tự khung trong câu chọn khung (PRD R-23 v2.1): nhắc lại giờ, ngày hay thứ tự khung là
# khẳng định rõ ("Đúng rồi, 15 giờ", "vâng, ba giờ chiều được", "khung hai"). Chỉ bỏ một CỤM thời gian (có
# từ neo hoặc chữ số); khung nhắc tới có đúng là khung đang chốt hay không do Dialogue đối chiếu.
_TIME_NUMBER_WORDS = frozenset(
    clean(w)
    for w in [
        "một", "hai", "ba", "bốn", "tư", "năm", "sáu", "bảy", "tám", "chín", "mười", "mươi",
        "mốt", "lăm", "nhăm", "linh", "lẻ",
    ]
)  # fmt: skip
_TIME_ANCHORS = frozenset(
    clean(w)
    for w in [
        "giờ", "h", "rưỡi", "phút", "kém", "sáng", "trưa", "chiều", "tối", "thứ", "chủ", "nhật",
        "ngày", "tháng", "hôm", "mai", "buổi", "đầu", "tiên", "nhất", "cuối", "tuần",
    ]
)  # fmt: skip
_TIME_LINKS = frozenset(clean(w) for w in ["lúc", "vào", "cái", "số", "này", "nay", "tới", "sau"])
_ORDINAL_PHRASES = (_ORDINAL, _HOUR_ORDINAL, _FIRST, _LAST)


def strip_slot_phrases(text: str) -> str:
    """Bỏ các cụm thứ tự khung và cụm thời gian khỏi câu đã `clean` (chỉ nhận từ có dấu).

    Cụm thứ tự lấy đúng các mẫu `extract_slot_choice` nhận ("khung hai", "cái số một", "cái đầu tiên"), để
    mọi cách gọi khung mà IE hiểu được đều được bỏ như nhau.
    """
    for pattern in _ORDINAL_PHRASES:
        text = " ".join(pattern.sub(" ", text).split())
    words = text.split()
    kept: list[str] = []
    run: list[str] = []

    def flush() -> None:
        has_anchor = any(w in _TIME_ANCHORS or w.isdigit() or _is_clock(w) for w in run)
        if not has_anchor:
            kept.extend(run)
        run.clear()

    for word in words:
        if (
            word in _TIME_ANCHORS
            or word in _TIME_NUMBER_WORDS
            or word in _TIME_LINKS
            or word.isdigit()
            or _is_clock(word)
        ):
            run.append(word)
        else:
            flush()
            kept.append(word)
    flush()
    return " ".join(kept)


def _is_clock(word: str) -> bool:
    """ "15h", "15h30", "9g" sau khi bỏ dấu câu ("15:30" đã tách thành hai số)."""
    return re.fullmatch(r"\d{1,2}(?:h|g)(?:\d{2})?", word) is not None


def asks_back(transcript: str) -> bool:
    """Câu hỏi lại, không phải chọn: "sao lại…", hoặc kết thúc bằng "à" / "hả" / "hở"."""
    text = clean(transcript)
    if not text:
        return False
    if find_phrase(text, _ASKS_BACK) is not None:
        return True
    last = text.split()[-1]
    return last in _ASKS_BACK_FINALS if is_unaccented(text) else last in {"à", "hả", "hở"}


def requested_slot_count(transcript: str) -> Optional[int]:
    """Số khung người gọi xin nghe một lượt ("cho tôi xem 4 khung khác" -> 4); None nếu không nêu số."""
    match = _SLOT_COUNT.search(strip_diacritics(clean(normalize(transcript))))
    if match is None:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else _COUNT_WORDS.get(token)


def extract_slot_choice(
    transcript: str,
    slots: Sequence[dict[str, Any]],
    presented_slot_ids: Sequence[str],
    now: datetime,
) -> Field[SlotChoice]:
    transcript = _corrected(transcript)
    text = normalize(transcript)
    # "3 giờ chiều à không phải 10 giờ 30" là lời tự sửa (R-44, giữ giá trị sau), không phải loại 10:30
    excluded = None if _self_corrected(transcript, now) else _EXCLUSION.search(text)
    if excluded is not None and not parse_slot_criteria(excluded.group("out"), now).empty:
        # Phần bị loại chỉ đến hết mệnh đề: "không lấy giờ này, ngày 21 đi" — "ngày 21" là điều muốn
        rest = f"{text[: excluded.start()]} , {text[excluded.end() :]}"
        return _choice_with_exclusion(
            transcript, excluded.group("out"), rest, slots, presented_slot_ids, now
        )
    criteria = parse_slot_criteria(transcript, now)
    # "sớm hơn / muộn hơn" trần ở câu chọn khung là xin khung khác (T-10 R033/R034): sớm hơn khung vừa
    # đọc hay lịch cũ là mơ hồ. Có kèm ngày / buổi / giờ thì mới là yêu cầu mới.
    if replace(criteria, relative=None).empty:
        text = clean(transcript)
        any_time = find_phrase(text, _ANY)
        if any_time is not None:
            return Field(SlotChoice("ANY"), Provenance.NORMALIZED, span=any_time.group(0))
        more = find_phrase(text, _MORE)
        if more is not None:
            return Field(SlotChoice("MORE"), Provenance.NORMALIZED, span=more.group(0))
        count = _SLOT_COUNT.search(strip_diacritics(text))
        if count is not None:
            span = text[count.start() : count.end()]
            return Field(SlotChoice("MORE"), Provenance.NORMALIZED, span=span)
        return Field.nothing(SlotChoice("NO_MATCH"))

    matched = tuple(s["slot_id"] for s in filter_slots(slots, criteria, presented_slot_ids))
    span = clean(transcript)
    if len(matched) == 1:
        return Field(SlotChoice("MATCH", matched, criteria), Provenance.NORMALIZED, span=span)
    if matched:
        return Field(SlotChoice("AMBIGUOUS", matched, criteria), Provenance.NORMALIZED, span=span)
    return Field(SlotChoice("NO_MATCH", (), criteria), Provenance.NORMALIZED, span=span)


# Tự sửa: "không phải khung 1 mà là khung 2" -> chỉ đọc phần sau "mà (là)"; "khung 2 chứ không phải
# khung 1" -> chỉ đọc phần trước "chứ không phải". Không chọn theo lần khớp đầu tiên của cả câu.
_CORRECTION = re.compile(r"(?<!\w)không phải\s+.+?\s+mà(?:\s+là)?\s+(?P<keep>.+)$")
_KEEP_BEFORE = re.compile(r"^(?P<keep>.+?)\s+chứ không phải(?!\w)")
# Loại trừ: "trừ khung 1", "khung nào cũng được trừ 10 giờ", "không lấy khung 1"
_EXCLUSION = re.compile(
    r"(?<!\w)(?:ngoại trừ|trừ(?! khi)|không lấy|không chọn|không phải|đừng lấy|đừng chọn|bỏ)"
    r"\s+(?P<out>[^,;.!?…]+)"
)


def _corrected(transcript: str) -> str:
    """Phần người gọi giữ lại, cắt trên bản còn dấu câu: "không phải 14/10 mà là 15/10" -> "15/10"
    (`clean` tách "15/10" thành hai số, mất ngày)."""
    text = clean(transcript)
    match = _CORRECTION.search(text)
    if match is not None:
        return drop_leading_words(transcript, len(text[: match.start("keep")].split()))
    match = _KEEP_BEFORE.search(text)
    if match is not None:
        return keep_leading_words(transcript, len(match.group("keep").split()))
    return transcript


def _choice_with_exclusion(
    transcript: str,
    excluded: str,
    rest: str,
    slots: Sequence[dict[str, Any]],
    presented_slot_ids: Sequence[str],
    now: datetime,
) -> Field[SlotChoice]:
    """Khung bị loại bỏ khỏi các khung vừa đọc (hoặc mọi khung khi chưa đọc khung nào), trong số
    khung thỏa phần còn lại của câu. Còn đúng một khung thì chọn nó — vẫn phải đọc lại để xác nhận;
    còn nhiều thì hỏi lại trong số đó."""
    span = clean(transcript)
    out = parse_slot_criteria(excluded, now)
    wanted = parse_slot_criteria(rest, now)
    out_ids = {s["slot_id"] for s in filter_slots(slots, out, presented_slot_ids)}
    if not wanted.empty:
        pool = filter_slots(slots, wanted, presented_slot_ids)
    elif presented_slot_ids:
        pool = [s for s in slots if s["slot_id"] in presented_slot_ids]
    else:
        pool = list(slots)
    kept = tuple(s["slot_id"] for s in pool if s["slot_id"] not in out_ids)
    if len(kept) == 1:
        return Field(SlotChoice("MATCH", kept, wanted), Provenance.NORMALIZED, span=span)
    if kept:
        return Field(SlotChoice("AMBIGUOUS", kept, wanted), Provenance.NORMALIZED, span=span)
    return Field(SlotChoice("NO_MATCH", (), wanted), Provenance.NORMALIZED, span=span)


def filter_slots(
    slots: Iterable[dict[str, Any]], criteria: SlotCriteria, presented_slot_ids: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Dùng chung cho Dialogue Manager (lọc trước khi đọc slot) — thứ tự giữ nguyên như GET /slots."""
    ordinal_id = _ordinal_slot_id(criteria.ordinal, presented_slot_ids)
    if criteria.ordinal is not None and ordinal_id is None:
        return []
    return [s for s in slots if _matches(s, criteria, ordinal_id)]


def parse_slot_criteria(transcript: str, now: datetime) -> SlotCriteria:
    """Tiêu chí của phần người gọi giữ lại: "không phải 14/10 mà là 15/10" -> 15/10 (`_corrected`), "ngày
    15… à không, 14" -> 14 (`_corrected_criteria`). IE và Dialogue (yêu cầu mới) đọc cùng một cách."""
    text = _prepare(_corrected(transcript))
    today = to_local(now).date()
    corrected = _corrected_criteria(text, today)
    found = corrected[1] if corrected is not None else _criteria(text, today, {})
    _check_dates(today, found)
    return SlotCriteria(**found)


def anchor_relative(criteria: SlotCriteria, anchor: datetime) -> SlotCriteria:
    """Gắn mốc cho "sớm hơn" / "muộn hơn": `anchor` là giờ bắt đầu của lịch hẹn đang đổi."""
    if criteria.relative == "EARLIER":
        return replace(criteria, earlier_than=anchor)
    if criteria.relative == "LATER":
        return replace(criteria, later_than=anchor)
    return criteria


def _self_corrected(transcript: str, now: datetime) -> bool:
    return _corrected_criteria(_prepare(transcript), to_local(now).date()) is not None


def without_corrected_part(transcript: str, now: datetime) -> str:
    """Bỏ phần bị sửa: "9 giờ, à không, 10 giờ" -> "10 giờ"; không có lời tự sửa thì giữ nguyên câu.

    Chỉ để đọc có / không trên câu trả lời sau cùng của người gọi (R-44): "không" trong "à không" là
    lời sửa giá trị, không phải lời từ chối khung đang chốt (R-41). Lời đồng ý thật vẫn đi qua
    `confirmation_veto` trên NGUYÊN câu.
    """
    corrected = _corrected_criteria(_prepare(transcript), to_local(now).date())
    return corrected[0] if corrected is not None else transcript


def _prepare(transcript: str) -> str:
    text = normalize(transcript)
    unaccented = is_unaccented(clean(text))
    if unaccented:
        text = _restore_unaccented(clean(text))
    text = _NUMERIC_TIME.sub(lambda m: f" {m.group(1)} giờ {m.group(2) or ''} ", text)
    text = _NUMERIC_DAY.sub(lambda m: f" ngày {m.group(1)} tháng {m.group(2)} ", text)
    text = clean(text)
    count = _SLOT_COUNT.search(strip_diacritics(text))
    if count is not None:
        text = _cut(text, count)
    return text


# R-44: cụm tự sửa, thêm vào `CORRECTIONS` của danh tính. Ở đây không có tên người nên "a khong" không dấu
# vẫn là "à không" ("khong" đã được khôi phục thành "không" như một từ số). "à" / "ờ" / "ơ" trần chỉ nhận
# bản có dấu ("o" không dấu có thể là "ở"); mọi cụm chỉ được tính khi hai bên đều nêu tiêu chí.
_CORRECTIONS = compile_phrases(
    [
        "à không phải",
        "ờ không",
        "ơ không",
        "à mà không",
        "a không",
        "a không phải",
        "a nhầm",
        "mà thôi",
        "thôi để",
    ]
)
_SOFT_CORRECTIONS = compile_phrases(["à", "ờ", "ơ"], unaccented_exclude=["à", "ờ", "ơ"])
# Số trần ở phần sửa mượn đơn vị của số bị sửa: đứng trước số ("ngày 15") hoặc sau số ("9 giờ")
_UNIT_BEFORE = frozenset({"ngày", "mùng", "mồng", "thứ", "khung", "số"})
_UNIT_AFTER = frozenset({"giờ", "rưỡi", "tháng"})
_ORDINAL_TAIL = re.compile(r"^(?:thứ|số)\s+(?:nhất|một|hai|ba|tư|bốn|năm|[1-9])$")


def _corrected_criteria(text: str, today: date) -> Optional[tuple[str, dict[str, Any]]]:
    """(phần sửa, tiêu chí) của lời tự sửa sau cùng có hai bên đều nêu tiêu chí; `None` khi không có.

    Phần trước lời sửa vẫn được đọc, để giữ những tiêu chí phần sửa không nhắc lại.
    """
    for head, spoken in _correction_splits(text):
        head_found = _criteria(head, today, {})
        if not head_found:
            continue
        tail = _complete_tail(head, spoken, head_found)
        tail_found = _criteria(tail, today, {})
        if not tail_found:
            continue
        if "ordinal" in tail_found:
            # "khung 1, à không, khung 2": chọn theo thứ tự thay cả cách chọn cũ
            return spoken, tail_found
        seed = {k: v for k, v in head_found.items() if k not in ("ordinal", "date_issue")}
        if _TIME_KEYS & tail_found.keys():
            # Giờ / khoảng giờ mới thay giờ và khoảng giờ cũ. Buổi của giờ cũ vẫn giữ ("2 giờ chiều, à nhầm,
            # 3 giờ" là 15:00), trừ khi giờ mới đi với buổi đó thành giờ ngoài ngày làm việc: "3 giờ
            # chiều, à không phải, 10 giờ 30" là 10:30, không phải 22:30
            hours = tail_found.get("hours")
            period = seed.get("period")
            if hours and period and "period" not in tail_found:
                if not any(6 <= h <= 20 for h in _candidate_hours(min(hours), period)):
                    seed.pop("period")
            seed = {k: v for k, v in seed.items() if k not in _TIME_KEYS}
        merged = _criteria(tail, today, seed)
        if "period" in tail_found and "hours" not in tail_found and "hours" in seed:
            # "9 giờ sáng, à không, chiều": giờ cũ đọc lại theo buổi mới
            hour = min(seed["hours"])
            if hour < 12:
                merged["hours"] = _candidate_hours(hour, merged["period"])
        return spoken, merged
    return None


_TIME_KEYS = frozenset({"hours", "minute", "not_before", "before"})


def _correction_splits(text: str) -> list[tuple[str, str]]:
    """(phần trước, phần sau) của mỗi cụm tự sửa, cụm kết thúc muộn nhất trước."""
    matches: list[re.Match[str]] = []
    phrase_sets: tuple[PhraseSet, ...] = (CORRECTIONS, _CORRECTIONS, _SOFT_CORRECTIONS)
    for phrases in phrase_sets:
        matches += [m for _, p in phrases.for_text(text, mixed=True) for m in p.finditer(text)]
    splits = []
    for match in sorted(matches, key=lambda m: (m.end(), m.end() - m.start()), reverse=True):
        head, tail = text[: match.start()].strip(), text[match.end() :].strip()
        if head and tail:
            splits.append((head, tail))
    return splits


def _complete_tail(head: str, tail: str, head_found: dict[str, Any]) -> str:
    """ "thứ Sáu ngày 15… à không, 14" -> phần sửa "ngày 14"; "khung thứ nhất, à không, thứ hai" -> "khung thứ hai"."""
    words = tail.split()
    if "ordinal" in head_found and _ORDINAL_TAIL.match(tail):
        return f"khung {tail}"
    # Chỉ số trần đứng đầu phần sửa ("16 được không"); "10 giờ", "15 tháng 10" đã tự có đơn vị
    lead = len(_number_run(words))
    if lead == 0 or (lead < len(words) and words[lead] in _UNIT_AFTER):
        return tail
    number, rest = " ".join(words[:lead]), " ".join(words[lead:])
    tokens = head.split()
    end = max((i for i, t in enumerate(tokens) if is_number_token(t)), default=None)
    if end is None:
        return tail
    start = end
    while start > 0 and is_number_token(tokens[start - 1]):
        start -= 1
    if start > 0 and tokens[start - 1] in _UNIT_BEFORE:
        return f"{tokens[start - 1]} {number} {rest}".strip()
    if end + 1 < len(tokens) and tokens[end + 1] in _UNIT_AFTER:
        return f"{number} {tokens[end + 1]} {rest}".strip()
    return tail


def _criteria(text: str, today: date, seed: dict[str, Any]) -> dict[str, Any]:
    """Tiêu chí rút từ `text`, chưa kiểm ngày (`_check_dates`). `seed`: tiêu chí giữ lại từ trước lời sửa."""
    found: dict[str, Any] = dict(seed)

    text = _take_ordinal(text, found)
    text = _take_relative(text, found)
    text = _take_relative_dates(text, today, found)
    text = _take_weekday(text, found)
    text = _take_day_of_month(text, found)
    text = _take_month(text, today, found)
    text = _take_period(text, found)
    _take_time(text, found)
    return found


def resolve_request(criteria: SlotCriteria, now: datetime) -> SlotCriteria:
    """Quy đổi thứ trần của MỘT YÊU CẦU MỚI theo R-30: "thứ Sáu", "thứ Sáu này" = thứ Sáu tuần này.

    Đã qua -> PAST; trùng hôm nay -> TODAY (hỏi hôm nay hay tuần sau). Không áp dụng khi người gọi
    chọn trong các khung vừa đọc ("cái thứ Sáu ấy" khớp thứ Sáu trong danh sách).
    """
    if criteria.weekday is None or criteria.day is not None or criteria.date_from is not None:
        return criteria
    if criteria.date_issue is not None:
        return criteria
    today = to_local(now).date()
    target = today + timedelta(days=criteria.weekday - today.weekday())
    issue = "PAST" if target < today else "TODAY" if target == today else None
    return replace(criteria, date_from=target, date_to=target, date_issue=issue)


def _restore_unaccented(text: str) -> str:
    for pattern, accented in _UNACCENTED_PHRASE_RE:
        text = pattern.sub(accented, text)
    text = _UNACCENTED_WEEKDAY_DIGIT.sub("thứ ", text)

    restored: list[str] = []
    tokens = text.split()
    for i, token in enumerate(tokens):
        previous = restored[-1] if restored else None
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if token in ("sang", "toi") and previous in _PERIOD_AFTER:
            restored.append("sáng" if token == "sang" else "tối")
        elif token == "sau" and following in ("gio", "ruoi"):
            restored.append("sáu")
        elif token == "so" and following is not None and is_number_token(following):
            restored.append("số")
        else:
            restored.append(_UNACCENTED_WORDS.get(token, token))
    return " ".join(restore_number_words(restored))


# --- Trích tiêu chí -------------------------------------------------------------
# Mỗi hàm _take_* ghi vào `found` và xoá đoạn đã dùng khỏi text, để "thứ hai" của
# "khung thứ hai" không bị đọc lại thành thứ Hai, "năm" của "thứ năm" không thành 5 giờ.


def _take_ordinal(text: str, found: dict[str, Any]) -> str:
    match = _ORDINAL.search(text)
    if match:
        token = match.group(1)
        found["ordinal"] = int(token) if token.isdigit() else _ORDINAL_WORDS[token]
        return _cut(text, match)
    match = _HOUR_ORDINAL.search(text)
    before = text[: match.start()].split() if match else []
    if match and not (before and is_number_token(before[-1])):
        token = match.group(1)
        found["ordinal"] = int(token) if token.isdigit() else _ORDINAL_WORDS[token]
        return _cut(text, match)
    for pattern, value in ((_FIRST, 1), (_LAST, -1)):
        match = pattern.search(text)
        if match:
            found["ordinal"] = value
            return _cut(text, match)
    return text


def _take_relative(text: str, found: dict[str, Any]) -> str:
    for relative, phrases in _RELATIVE.items():
        match = find_phrase(text, phrases)
        if match is not None:
            found["relative"] = relative
            return _cut(text, match)
    return text


def _take_relative_dates(text: str, today: date, found: dict[str, Any]) -> str:
    for pattern, offset in _RELATIVE_DAYS:
        match = pattern.search(text)
        if match:
            found["date_from"] = found["date_to"] = today + timedelta(days=offset)
            return _cut(text, match)
    monday = today - timedelta(days=today.weekday())
    match = _WEEK_AFTER_NEXT.search(text)
    if match:
        found["date_from"], found["date_to"] = _week(monday + timedelta(days=14))
        return _cut(text, match)
    match = _WEEK_PART.search(text)
    if match:
        start = monday + timedelta(days=7 if match.group(2) in ("sau", "tới") else 0)
        if match.group(1) == "đầu":
            found["date_from"], found["date_to"] = start, start + timedelta(days=2)
        else:
            found["date_from"], found["date_to"] = (
                start + timedelta(days=5),
                start + timedelta(days=6),
            )
        return _cut(text, match)
    match = _WEEK.search(text)
    if match:
        start = monday + timedelta(days=7 if match.group(1) in ("sau", "tới") else 0)
        found["date_from"], found["date_to"] = _week(start)
        return _cut(text, match)
    return text


def _week(monday: date) -> tuple[date, date]:
    return monday, monday + timedelta(days=6)


def _take_month(text: str, today: date, found: dict[str, Any]) -> str:
    """ "mùng 5 tháng sau" -> tháng sau; "tháng sau" / "cuối tháng" / "tháng 11" trần -> quá rộng."""
    match = _MONTH_RELATIVE.search(text)
    if match:
        if "day" in found and "month" not in found:
            found["month"] = today.month if match.group(1) == "này" else today.month % 12 + 1
        else:
            found["date_issue"] = "TOO_BROAD"
        return _cut(text, match)
    match = _MONTH_PART.search(text)
    if match:
        found["date_issue"] = "TOO_BROAD"
        return _cut(text, match)
    if "day" not in found and "tháng" in text.split():
        found["date_issue"] = "TOO_BROAD"
    return text


def _check_dates(today: date, found: dict[str, Any]) -> None:
    """R-30: ngày không tồn tại / đã qua -> hỏi lại. Khoảng ngày cắt phần đã qua, không bỏ cả khoảng."""
    if found.get("date_issue") is not None:
        return
    day, month = found.get("day"), found.get("month")
    if day is not None and month is not None:
        try:
            spoken = date(today.year, month, day)
        except ValueError:
            # 31/9, hoặc 29/2 khi cả năm nay lẫn năm sau không nhuận
            if not _valid(today.year + 1, month, day):
                found["date_issue"] = "INVALID"
            return
        if today - PAST_DATE_WINDOW <= spoken < today:
            found["date_issue"] = "PAST"
            found["date_from"] = found["date_to"] = spoken
        return
    date_to = found.get("date_to")
    if date_to is not None and date_to < today:
        found["date_issue"] = "PAST"
        found["date_from"] = date_to
    elif found.get("date_from") is not None and found["date_from"] < today:
        found["date_from"] = today


def _valid(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _take_weekday(text: str, found: dict[str, Any]) -> str:
    match = _WEEKDAY.search(text)
    if not match:
        return text
    if match.group(2):
        found["weekday"] = 6
    else:
        token = match.group(1)
        found["weekday"] = int(token) - 2 if token.isdigit() else _WEEKDAY_INDEX[token]
    return _cut(text, match)


def _take_day_of_month(text: str, found: dict[str, Any]) -> str:
    """Ưu tiên "ngày D tháng M" hơn "ngày D" trần; "ngày 2 giờ chiều" là giờ, không phải mùng 2."""
    tokens = text.split()
    best: tuple[int, int, int, int | None] | None = None
    for i, token in enumerate(tokens):
        prefixed = token in ("ngày", "mùng", "mồng")
        # "16 tháng 10" không có chữ "ngày": chỉ nhận khi ngay sau số là "tháng"
        first = i + 1 if prefixed else i
        day, used = _longest_prefix_number(tokens[first:], 1, 31)
        if day is None:
            continue
        end = first + used
        if not prefixed and (end >= len(tokens) or tokens[end] != "tháng"):
            continue
        if end < len(tokens) and tokens[end] in ("giờ", "rưỡi"):
            continue
        month = None
        if end < len(tokens) and tokens[end] == "tháng":
            month, month_used = _longest_prefix_number(tokens[end + 1 :], 1, 12)
            if month is not None:
                end += 1 + month_used
        if best is None or month is not None:
            best = (i, end, day, month)
        if month is not None:
            break
    if best is None:
        return text
    start, end, found["day"], month = best
    if month is not None:
        found["month"] = month
    return " ".join(tokens[:start] + tokens[end:])


def _take_period(text: str, found: dict[str, Any]) -> str:
    tokens = text.split()
    for i, token in enumerate(tokens):
        if token in _PERIOD_WORDS:
            found["period"] = _PERIOD_WORDS[token]
            return " ".join(tokens[:i] + tokens[i + 1 :])
    return text


def _take_time(text: str, found: dict[str, Any]) -> None:
    tokens = text.split()
    for i, token in enumerate(tokens):
        if token not in ("giờ", "rưỡi"):
            continue
        hour, size = _longest_suffix_number(tokens[:i], 0, 23)
        if hour is None:
            continue
        bound = tokens[i - size - 1] if i - size - 1 >= 0 else None
        minute = 30 if token == "rưỡi" else 0
        after = tokens[i + 1 :]
        if token != "rưỡi" and after:
            if after[0] == "rưỡi":
                minute = 30
            elif after[0] == "kém":
                less, _ = _longest_prefix_number(after[1:], 1, 59)
                if less is not None:
                    hour, minute = (hour - 1) % 24, 60 - less
            else:
                parsed, _ = _longest_prefix_number(after, 0, 59)
                minute = parsed if parsed is not None else 0
        if bound in _RANGE_BOUNDS:
            # "sau 10 giờ 30": khoảng giờ, không phải khung 10:30
            hour = _daytime_hour(_candidate_hours(hour, found.get("period")))
            if bound == "trước":
                found["before"] = hour * 60 + minute
            else:
                # "từ 10 giờ" gồm cả 10:00; "sau 10 giờ" thì không
                found["not_before"] = hour * 60 + minute + (1 if bound == "sau" else 0)
            return
        found["hours"] = _candidate_hours(hour, found.get("period"))
        found["minute"] = minute
        return


_RANGE_BOUNDS = frozenset({"sau", "từ", "trước"})


def _daytime_hour(hours: frozenset[int]) -> int:
    """Giờ ứng viên trong giờ làm việc ("sau 2 giờ" -> 14h); không có thì giờ nhỏ nhất."""
    daytime = sorted(h for h in hours if 6 <= h <= 20)
    return daytime[0] if daytime else min(hours)


def _candidate_hours(hour: int, period: Optional[DayPeriod]) -> frozenset[int]:
    if hour > 12 or hour == 0:
        return frozenset({hour})
    if period == "MORNING":
        return frozenset({hour % 12})  # "12 giờ sáng" hiếm; coi như 0h
    if period == "NOON":
        return frozenset({hour if hour >= 11 else hour + 12})
    if period in ("AFTERNOON", "EVENING"):
        return frozenset({hour + 12 if hour < 12 else 12})
    # Không có buổi: "hai giờ rưỡi" -> 02:30 hoặc 14:30, danh sách slot quyết định
    return frozenset({hour, (hour + 12) % 24})


# --- So khớp slot ----------------------------------------------------------------


def requested_date(criteria: SlotCriteria, now: datetime) -> Optional[date]:
    """Ngày người gọi xin đổi sang (mốc R-29), hoặc None khi câu không nêu một ngày cụ thể.

    - "ngày 16 tháng 10" -> 16/10; đã qua thì năm sau. "ngày 16" -> ngày 16 gần nhất sắp tới.
    - "mai", "thứ Sáu tuần sau" -> ngày đầu của khoảng có đúng thứ đó.
    - Chỉ "thứ Sáu" hay chỉ buổi / giờ -> None (bước 6, R-30, mới quy đổi thứ trần).
    Ngày không tồn tại ("31 tháng 9") -> None.
    """
    today = to_local(now).date()
    if criteria.date_issue is not None:
        return None
    if criteria.day is not None:
        if criteria.month is not None:
            candidates = [(today.year, criteria.month), (today.year + 1, criteria.month)]
        else:
            next_month = (today.year + today.month // 12, today.month % 12 + 1)
            candidates = [(today.year, today.month), next_month]
        for year, month in candidates:
            try:
                day = date(year, month, criteria.day)
            except ValueError:
                continue
            if day >= today:
                return day
        return None
    if criteria.date_from is not None:
        day = criteria.date_from
        end = criteria.date_to or day
        while criteria.weekday is not None and day.weekday() != criteria.weekday and day < end:
            day += timedelta(days=1)
        return day
    return None


def _matches(slot: dict[str, Any], c: SlotCriteria, ordinal_id: Optional[str]) -> bool:
    if c.date_issue is not None:
        return False
    if ordinal_id is not None and slot["slot_id"] != ordinal_id:
        return False
    starts = to_local(datetime.fromisoformat(slot["starts_at"]))
    if c.hours is not None and starts.hour not in c.hours:
        return False
    if c.minute is not None and starts.minute != c.minute:
        return False
    minutes = starts.hour * 60 + starts.minute
    if c.not_before is not None and minutes < c.not_before:
        return False
    if c.before is not None and minutes >= c.before:
        return False
    # Có giờ cụ thể thì buổi đã được dùng để chọn giờ 24h; "6 giờ chiều" (18:00) nằm ngoài khoảng "chiều"
    if c.period is not None and c.hours is None and starts.hour not in _PERIOD_HOURS[c.period]:
        return False
    if c.weekday is not None and starts.weekday() != c.weekday:
        return False
    if c.day is not None and starts.day != c.day:
        return False
    if c.month is not None and starts.month != c.month:
        return False
    if c.date_from is not None and starts.date() < c.date_from:
        return False
    if c.date_to is not None and starts.date() > c.date_to:
        return False
    if c.relative is not None and c.earlier_than is None and c.later_than is None:
        return False  # chưa có mốc: là yêu cầu mới, không chọn được khung nào
    if c.earlier_than is not None and starts >= c.earlier_than:
        return False
    if c.later_than is not None and starts <= c.later_than:
        return False
    return True


def _ordinal_slot_id(ordinal: Optional[int], presented: Sequence[str]) -> Optional[str]:
    if ordinal is None or not presented:
        return None
    if ordinal == -1:
        return presented[-1]
    return presented[ordinal - 1] if 1 <= ordinal <= len(presented) else None


def _cut(text: str, match: re.Match[str]) -> str:
    return " ".join((text[: match.start()] + " " + text[match.end() :]).split())


def _longest_prefix_number(tokens: Sequence[str], low: int, high: int) -> tuple[Optional[int], int]:
    run = _number_run(tokens)
    for size in range(min(len(run), 3), 0, -1):
        value = parse_number(run[:size])
        if value is not None and low <= value <= high:
            return value, size
    return None, 0


def _longest_suffix_number(tokens: Sequence[str], low: int, high: int) -> tuple[Optional[int], int]:
    run = list(reversed(_number_run(list(reversed(tokens)))))
    for size in range(min(len(run), 3), 0, -1):
        value = parse_number(run[-size:])
        if value is not None and low <= value <= high:
            return value, size
    return None, 0


def _number_run(tokens: Sequence[str]) -> list[str]:
    run: list[str] = []
    for token in tokens:
        if not is_number_token(token):
            break
        run.append(token)
    return run
