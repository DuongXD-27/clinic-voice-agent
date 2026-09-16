"""Chọn slot — thiết kế v1.1 §5.7.

Lời người gọi chỉ được biến thành TIÊU CHÍ LỌC trên tập slot `GET /slots` của chính cuộc gọi này.
Không bao giờ dựng mốc thời gian mới từ lời nói, nên SF-02 không xảy ra được về mặt cấu trúc.

- MATCH(slot_id)      đúng 1 slot thoả mọi tiêu chí
- AMBIGUOUS(slot_ids) nhiều slot -> bot đọc tối đa 3 slot trong số đó, hỏi lại (không tự chọn slot đầu)
- NO_MATCH            không slot nào, hoặc không rút ra được tiêu chí nào

Ngày tương đối ("mai", "thứ năm tuần sau") tính theo ngày cuộc gọi, múi giờ +07:00.

Transcript không dấu: khôi phục dấu cho bảng từ ngày giờ đóng trước khi parse. "sang"/"toi" chỉ thành
"sáng"/"tối" khi đứng sau "giờ"/"rưỡi"/"buổi" — "doi sang chieu" là "đổi sang chiều", "toi muon" là "tôi muốn".
Khôi phục sai chỉ làm lệch tiêu chí lọc (NO_MATCH / AMBIGUOUS); slot vẫn chỉ lấy từ GET /slots và vẫn phải đọc lại.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

from callbot.engine.extraction.schema import (
    DayPeriod,
    Field,
    Provenance,
    SlotChoice,
    SlotCriteria,
    to_local,
)
from callbot.engine.extraction.spoken_numbers import (
    is_number_token,
    parse_number,
    restore_number_words,
)
from callbot.engine.extraction.text import clean, is_unaccented, normalize

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
_FIRST = re.compile(r"(?<!\w)(?:đầu tiên|cái đầu|khung đầu|slot đầu)(?!\w)")
_LAST = re.compile(r"(?<!\w)(?:cái cuối|khung cuối|slot cuối|sau cùng|cuối cùng)(?!\w)")

_RELATIVE_DAYS = [
    (re.compile(r"(?<!\w)hôm nay(?!\w)"), 0),
    (re.compile(r"(?<!\w)(?:ngày kia|ngày mốt|ngày mai kia)(?!\w)"), 2),
    (re.compile(r"(?<!\w)(?:ngày mai|mai)(?!\w)"), 1),
]
_WEEK = re.compile(r"(?<!\w)tuần (sau|tới|này)(?!\w)")
_WEEKDAY = re.compile(r"(?<!\w)(?:thứ\s+(hai|ba|tư|năm|sáu|bảy|[2-7])|(chủ nhật))(?!\w)")
_WEEKDAY_INDEX = {"hai": 0, "ba": 1, "tư": 2, "năm": 3, "sáu": 4, "bảy": 5}

# Chuẩn hoá dạng số trước khi bỏ dấu câu: "14h30", "14:30" -> "14 giờ 30"; "20/10" -> "ngày 20 tháng 10"
_NUMERIC_TIME = re.compile(r"(?<!\d)(\d{1,2})\s*(?:h|:|g)\s*(\d{2})?(?!\w)")
_NUMERIC_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\s*/)(?!\d)")

_UNACCENTED_PHRASES = {
    "hom nay": "hôm nay",
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


def extract_slot_choice(
    transcript: str,
    slots: Sequence[dict[str, Any]],
    presented_slot_ids: Sequence[str],
    now: datetime,
) -> Field[SlotChoice]:
    criteria = parse_slot_criteria(transcript, now)
    if criteria.empty:
        return Field.nothing(SlotChoice("NO_MATCH"))

    matched = tuple(s["slot_id"] for s in filter_slots(slots, criteria, presented_slot_ids))
    span = clean(transcript)
    if len(matched) == 1:
        return Field(SlotChoice("MATCH", matched, criteria), Provenance.NORMALIZED, span=span)
    if matched:
        return Field(SlotChoice("AMBIGUOUS", matched, criteria), Provenance.NORMALIZED, span=span)
    return Field(SlotChoice("NO_MATCH", (), criteria), Provenance.NORMALIZED, span=span)


def filter_slots(
    slots: Iterable[dict[str, Any]], criteria: SlotCriteria, presented_slot_ids: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Dùng chung cho Dialogue Manager (lọc trước khi đọc slot) — thứ tự giữ nguyên như GET /slots."""
    ordinal_id = _ordinal_slot_id(criteria.ordinal, presented_slot_ids)
    if criteria.ordinal is not None and ordinal_id is None:
        return []
    return [s for s in slots if _matches(s, criteria, ordinal_id)]


def parse_slot_criteria(transcript: str, now: datetime) -> SlotCriteria:
    text = normalize(transcript)
    unaccented = is_unaccented(clean(text))
    if unaccented:
        text = _restore_unaccented(clean(text))
    text = _NUMERIC_TIME.sub(lambda m: f" {m.group(1)} giờ {m.group(2) or ''} ", text)
    text = _NUMERIC_DAY.sub(lambda m: f" ngày {m.group(1)} tháng {m.group(2)} ", text)
    text = clean(text)
    today = to_local(now).date()
    found: dict[str, Any] = {}

    text = _take_ordinal(text, found)
    text = _take_relative_dates(text, today, found)
    text = _take_weekday(text, found)
    text = _take_day_of_month(text, found)
    text = _take_period(text, found)
    _take_time(text, found)
    return SlotCriteria(**found)


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
    for pattern, value in ((_FIRST, 1), (_LAST, -1)):
        match = pattern.search(text)
        if match:
            found["ordinal"] = value
            return _cut(text, match)
    return text


def _take_relative_dates(text: str, today: date, found: dict[str, Any]) -> str:
    for pattern, offset in _RELATIVE_DAYS:
        match = pattern.search(text)
        if match:
            found["date_from"] = found["date_to"] = today + timedelta(days=offset)
            return _cut(text, match)
    match = _WEEK.search(text)
    if match:
        monday = today - timedelta(days=today.weekday())
        if match.group(1) in ("sau", "tới"):
            monday += timedelta(days=7)
        found["date_from"], found["date_to"] = monday, monday + timedelta(days=6)
        return _cut(text, match)
    return text


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
    tokens = text.split()
    for i, token in enumerate(tokens):
        if token not in ("ngày", "mùng", "mồng"):
            continue
        day, used = _longest_prefix_number(tokens[i + 1 :], 1, 31)
        if day is None:
            continue
        found["day"] = day
        end = i + 1 + used
        if end < len(tokens) and tokens[end] == "tháng":
            month, month_used = _longest_prefix_number(tokens[end + 1 :], 1, 12)
            if month is not None:
                found["month"] = month
                end += 1 + month_used
        return " ".join(tokens[:i] + tokens[end:])
    return text


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
        hour, _ = _longest_suffix_number(tokens[:i], 0, 23)
        if hour is None:
            continue
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
        found["hours"] = _candidate_hours(hour, found.get("period"))
        found["minute"] = minute
        return


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


def _matches(slot: dict[str, Any], c: SlotCriteria, ordinal_id: Optional[str]) -> bool:
    if ordinal_id is not None and slot["slot_id"] != ordinal_id:
        return False
    starts = to_local(datetime.fromisoformat(slot["starts_at"]))
    if c.hours is not None and starts.hour not in c.hours:
        return False
    if c.minute is not None and starts.minute != c.minute:
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
