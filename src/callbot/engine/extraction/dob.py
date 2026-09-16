"""Ngày sinh — thiết kế v1.1 §5.2.

Hướng hiệu chỉnh: thà `INVALID` (hỏi lại, rồi chuyển máy) còn hơn ra một ngày sai.
Một ngày sai đi tiếp vào Verifier; một `INVALID` chỉ tốn một lượt hỏi lại.
Vì vậy mọi chỗ mơ hồ ở đây đều trả `INVALID` — đừng "sửa cho thông minh hơn":
- không tự sửa 31/02 về ngày gần nhất,
- không điền năm hiện tại khi thiếu năm,
- năm 2 chữ số khớp được cả hai thế kỷ -> `INVALID`,
- tự sửa trong câu mà phần sau không đủ ngày/tháng/năm -> `INVALID`.

Transcript không dấu ("muoi bon thang ba nam bay tam"): khôi phục dấu cho bảng từ đóng (số, ngày/tháng/
năm, từ tự sửa) rồi parse như thường. Khôi phục sai chỉ làm ra INVALID hoặc một ngày không khớp hồ sơ,
tức là từ chối nhầm ở Verifier — hướng an toàn.
"""

import re
from datetime import date
from typing import Optional

from callbot.engine.extraction.schema import INVALID, DobValue, Field, Provenance
from callbot.engine.extraction.spoken_numbers import (
    is_number_token,
    parse_number,
    restore_number_words,
    spoken_digits,
)
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_last_phrase,
    is_unaccented,
    normalize,
)

MAX_AGE = 110

# "14/3/1978", "14-03-78", "14.3" -> "14 tháng 3 năm 1978" để đi chung một ngữ pháp với dạng nói
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?(?!\d)")
_CORRECTIONS = compile_phrases(
    [
        "à không",
        "à nhầm",
        "nhầm",
        "nhầm rồi",
        "không phải",
        "à quên",
        "xin lỗi",
        "ý là",
        "ý tôi là",
        "ý em là",
        "sửa lại",
        "à thôi",
        "à mà không",
    ]
)
_LUNAR = compile_phrases(["âm lịch", "âm", "lịch âm"])
_AGE = compile_phrases(["tuổi"])
_FILLERS = frozenset(
    {
        "dạ",
        "vâng",
        "ạ",
        "à",
        "ờ",
        "ừ",
        "sinh",
        "ngày",
        "là",
        "em",
        "tôi",
        "con",
        "cháu",
        "mình",
        "của",
    }
)
# Bảng từ đóng cho transcript không dấu. "sau" -> sáu, "tu" -> tư: trong câu trả lời ngày sinh
# hai từ này gần như chỉ là số.
_UNACCENTED_WORDS = {
    "ngay": "ngày",
    "thang": "tháng",
    "mung": "mùng",
    "mong": "mồng",
    "sau": "sáu",
    "tu": "tư",
    "lam": "lăm",
    "am": "âm",
    "lich": "lịch",
    "tuoi": "tuổi",
    "a": "à",
    "nham": "nhầm",
    "phai": "phải",
    "loi": "lỗi",
    "quen": "quên",
    "y": "ý",
    "la": "là",
    "toi": "tôi",
    "sua": "sửa",
    "lai": "lại",
    "thoi": "thôi",
    "da": "dạ",
    "vang": "vâng",
    "roi": "rồi",
    "cua": "của",
    "minh": "mình",
    "chau": "cháu",
}


def extract_dob(transcript: str, today: date) -> Field[DobValue]:
    original = clean(transcript)
    # Nhận biết không dấu trên câu gốc, trước khi "14/3" được đổi thành "ngày 14 tháng 3" có dấu
    restored = is_unaccented(original)
    converted = _NUMERIC_DATE.sub(_numeric_to_words, normalize(transcript))
    text = clean(converted)
    if restored:
        text = " ".join(restore_number_words(text.split(), _UNACCENTED_WORDS))
    if not text:
        return Field.nothing()

    if find_last_phrase(text, _LUNAR, unaccented=False) is not None:
        # Âm lịch -> hỏi lại theo dương lịch; không tự quy đổi
        return Field(INVALID, Provenance.NORMALIZED, span=original)

    correction = find_last_phrase(text, _CORRECTIONS, unaccented=False)
    segment = text[correction.end() :].strip() if correction else text
    tokens = segment.split()
    provenance = (
        Provenance.NORMALIZED if restored or _uses_spoken_numbers(tokens) else Provenance.EXACT
    )

    value = _parse_tokens(tokens, today)
    if value is None:
        if (
            correction is not None
            or _has_date_content(tokens)
            or find_last_phrase(text, _AGE, unaccented=False)
        ):
            return Field(INVALID, provenance, span=original)
        return Field.nothing()
    # span phải là chuỗi con của transcript: với câu không dấu, span là câu gốc chứ không phải bản đã khôi phục
    return Field(value, provenance, span=original if restored else segment)


def _uses_spoken_numbers(tokens: list[str]) -> bool:
    """Có số đọc bằng chữ không. "năm" đứng trước một số là từ khoá năm, không phải số 5."""
    return any(
        is_number_token(t)
        and not t.isdigit()
        and not (t == "năm" and i + 1 < len(tokens) and tokens[i + 1].isdigit())
        for i, t in enumerate(tokens)
    )


def _numeric_to_words(match: re.Match[str]) -> str:
    day, month, year = match.groups()
    return f" ngày {day} tháng {month}" + (f" năm {year} " if year else " ")


def _has_date_content(tokens: list[str]) -> bool:
    if "tháng" in tokens:
        return True
    if any(
        t == "năm" and i + 1 < len(tokens) and is_number_token(tokens[i + 1])
        for i, t in enumerate(tokens)
    ):
        return True
    numbers = [t for t in tokens if is_number_token(t)]
    return any(t.isdigit() for t in numbers) or len(numbers) >= 2


def _parse_tokens(tokens: list[str], today: date) -> Optional[DobValue]:
    """date | INVALID | None (không có nội dung ngày tháng)."""
    if tokens.count("tháng") > 1:
        return INVALID
    if "tháng" in tokens:
        return _parse_with_month_anchor(tokens, tokens.index("tháng"), today)
    return _parse_digit_sequence(tokens, today)


def _parse_with_month_anchor(tokens: list[str], at: int, today: date) -> DobValue:
    day_tokens = _number_run_before(tokens, at)
    day = parse_number(day_tokens) if day_tokens else None
    if day is None or not 1 <= day <= 31:
        return INVALID

    after = _number_run_after(tokens, at + 1)
    candidates: set[date] = set()
    saw_invalid = False
    for split in range(1, min(len(after), 3) + 1):
        month = parse_number(after[:split])
        if month is None or not 1 <= month <= 12:
            continue
        rest = after[split:]
        year_tokens: Optional[list[str]] = None
        if len(rest) > 1 and rest[0] == "năm":
            year_tokens = rest[1:]
        elif len(rest) == 1 and rest[0].isdigit():
            year_tokens = rest  # "14 tháng 3 1978"
        if year_tokens is None:
            continue  # thiếu năm: không điền năm hiện tại
        resolved = _resolve_date(day, month, year_tokens, today)
        if resolved is None:
            continue  # cách tách này không cho ra một năm đọc được
        if resolved is INVALID:
            saw_invalid = True
        else:
            candidates.add(resolved)

    if len(candidates) == 1 and not saw_invalid:
        return candidates.pop()
    return INVALID


def _parse_digit_sequence(tokens: list[str], today: date) -> Optional[DobValue]:
    """Không có "tháng": "14 3 1978", "14031978", "một bốn không ba một chín bảy tám"."""
    content = [t for t in tokens if t not in _FILLERS or is_number_token(t)]
    if not content or not all(is_number_token(t) for t in content):
        return None
    if len(content) == 1 and not content[0].isdigit():
        return None  # một từ số đứng một mình ("không") — không phải câu trả lời ngày sinh

    if len(content) == 3 and all(t.isdigit() for t in content):
        return _resolve_date(int(content[0]), int(content[1]), [content[2]], today) or INVALID
    digits = spoken_digits(content)
    if digits is None or len(digits) not in (6, 8):
        return INVALID
    return _resolve_date(int(digits[:2]), int(digits[2:4]), [digits[4:]], today) or INVALID


def _resolve_date(day: int, month: int, year_tokens: list[str], today: date) -> Optional[DobValue]:
    """None: dãy token không đọc được thành năm. INVALID: đọc được nhưng ngày không hợp lệ / mơ hồ."""
    if all(t.isdigit() for t in year_tokens):
        raw = "".join(year_tokens)
        if len(raw) == 2:
            return _resolve_two_digit_year(day, month, int(raw), today)
        if len(raw) != 4:
            return INVALID
        return _checked(day, month, int(raw), today)

    year = parse_number(year_tokens)
    if year is None:
        return None
    if year < 100:
        return _resolve_two_digit_year(day, month, year, today)
    if year < 1000:
        return INVALID
    return _checked(day, month, year, today)


def _resolve_two_digit_year(day: int, month: int, yy: int, today: date) -> DobValue:
    valid = [
        d
        for d in (_checked(day, month, century + yy, today) for century in (1900, 2000))
        if d is not INVALID
    ]
    # Cả hai thế kỷ đều cho tuổi hợp lệ ("năm 20" -> 1920 hay 2020) -> hỏi lại, không đoán
    return valid[0] if len(valid) == 1 else INVALID


def _checked(day: int, month: int, year: int, today: date) -> DobValue:
    try:
        born = date(year, month, day)
    except ValueError:
        return INVALID  # 31/02: không tự sửa về ngày gần nhất
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if born > today or age > MAX_AGE:
        return INVALID
    return born


def _number_run_before(tokens: list[str], end: int, max_len: int = 4) -> list[str]:
    start = end
    while start > 0 and end - start < max_len and is_number_token(tokens[start - 1]):
        start -= 1
    return tokens[start:end]


def _number_run_after(tokens: list[str], start: int, max_len: int = 12) -> list[str]:
    end = start
    while end < len(tokens) and end - start < max_len and is_number_token(tokens[end]):
        end += 1
    return tokens[start:end]
