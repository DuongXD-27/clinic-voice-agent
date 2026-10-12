"""Ngày sinh — thiết kế v1.1 §5.2.

Hướng hiệu chỉnh: thà `INVALID` (hỏi lại, rồi chuyển máy) còn hơn ra một ngày sai.
Một ngày sai đi tiếp vào Verifier; một `INVALID` chỉ tốn một lượt hỏi lại.
Vì vậy mọi chỗ mơ hồ ở đây đều trả `INVALID` — đừng "sửa cho thông minh hơn":
- không tự sửa 31/02 về ngày gần nhất,
- không điền năm hiện tại khi thiếu năm,
- năm 2 chữ số khớp được cả hai thế kỷ -> `INVALID`,
- tự sửa trong câu mà phần sau không đủ ngày/tháng/năm -> `INVALID`,
- người gọi tự báo là không chắc ("hình như", "thì phải") -> `INVALID`, hỏi lại,
- hai ngày cùng được nêu mà không có lời sửa ("14 hay 15 tháng 3") -> `INVALID`.

Phủ định khác tự sửa: "không phải A" bỏ A mà không có gì thay thế -> `INVALID`; chỉ
"không phải A mà là B" và "A, à nhầm B" mới lấy B, và chỉ khi B đủ ngày/tháng/năm.

Transcript mất dấu một phần ("ngày 14 thang 3 nam 1978"): khôi phục dấu theo *từng token*
cho bảng từ đóng (số, ngày/tháng/năm, từ tự sửa); token đã có dấu giữ nguyên. Khôi phục sai
chỉ làm ra INVALID hoặc một ngày không khớp hồ sơ, tức là từ chối nhầm ở Verifier — hướng an toàn.

`span` luôn là đoạn có thật trong `clean(transcript)`; vùng ngày được nhận ra nằm ở
`Reading.zone`, cũng là đoạn có thật — "14/3/1978" không bao giờ báo cáo thành đoạn
"ngày 14 tháng 3 năm 1978" mà bộ trích xuất tự dựng để đi chung ngữ pháp với dạng nói.
"""

import re
from datetime import date
from typing import Optional

from callbot.engine.extraction.identity import (
    AFFIRMATIONS,
    ALTERNATIVES,
    CORRECTIONS,
    NEGATIONS,
    UNCERTAINTY,
    Reading,
    Reason,
    english_hedge,
    english_no,
    token_index,
)
from callbot.engine.extraction.schema import INVALID, DobValue, Field, Provenance
from callbot.engine.extraction.spoken_numbers import (
    is_number_token,
    parse_spoken_number,
    restore_number_words,
    spoken_digits,
)
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_last_phrase,
    find_phrase,
    normalize,
    strip_punctuation,
)

MAX_AGE = 110

# "14 / 3 / 1978" -> "14/3/1978" để cả cụm nằm gọn trong một token nguồn
_TIGHTEN = re.compile(r"(?<=\d)\s*([/\-.])\s*(?=\d)")
# "14/3/1978", "14-03-78", "14.3" -> "ngày 14 tháng 3 năm 1978" để đi chung một ngữ pháp với dạng nói
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?")
# "1978-03-14" (ISO, năm đứng trước)
_ISO_DATE = re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")
_TRIM = ",.;:!?\"'()[]"
# Người gọi nói tiếng Anh (QC qc-w6-01): "March 14, 1978", "14th of March 1978", và ASR tiếng Anh
# ghi số bằng chữ: "March fourteenth, nineteen seventy-eight". Ngày thiếu năm ("April 15") vẫn được
# chuyển để kiểm tra thiếu năm / nhiều giá trị nhìn thấy nó.
EN_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_EN_DAY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?")
_EN_YEAR = re.compile(r"\d{2}|\d{4}")
# Số đọc bằng chữ tiếng Anh (QC qc-w6-01, 12/10/2026). Ngày: số đếm hoặc số thứ tự ("fourteen",
# "fourteenth", "twenty first"). Năm: hai cặp "nineteen seventy eight" / "twenty twenty" / "nineteen oh
# five", hoặc "two thousand (and) four", "nineteen hundred (and) seventy eight"; "seventy eight" là năm
# 2 chữ số như "78". Cặp sau chỉ một từ đơn vị ("twenty one") không nhận là năm hai cặp: 21 hay 2001.
_EN_UNITS = {
    "zero": 0,
    "oh": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_EN_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
}
_EN_ZERO = frozenset({"zero", "oh"})
_EN_CENTURIES = frozenset({19, 20})
_EN_YEAR_MAX_WORDS = 6  # "one thousand nine hundred seventy eight"
_LUNAR = compile_phrases(["âm lịch", "âm", "lịch âm"])
_AGE = compile_phrases(["tuổi"])
_DATE_WORDS = frozenset({"ngày", "tháng", "năm", "mùng", "mồng"})
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
# Bảng từ đóng cho token mất dấu. "sau" -> sáu, "tu" -> tư: trong câu trả lời ngày sinh
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
    return read_dob(transcript, today).field


def read_dob(transcript: str, today: date) -> Reading[DobValue]:
    text = clean(transcript)
    if not text:
        return Reading(Field.nothing(), Reason.NO_SIGNAL)
    words = text.split()
    spoken, origin, english_words = _parse_stream(transcript)
    tokens = restore_number_words(spoken, _UNACCENTED_WORDS)
    keep = _without_lead_ins(tokens)
    spoken = [spoken[i] for i in keep]
    origin = [origin[i] for i in keep]
    tokens = [tokens[i] for i in keep]
    provenance = (
        Provenance.NORMALIZED
        if tokens != spoken or _uses_spoken_numbers(tokens) or english_words
        else Provenance.EXACT
    )
    joined = " ".join(tokens)

    def invalid(reason: Reason, zone: Optional[str] = None) -> Reading[DobValue]:
        return Reading(Field(INVALID, provenance, span=text), reason, zone)

    if find_last_phrase(joined, _LUNAR, mixed=True) is not None:
        # Âm lịch -> hỏi lại theo dương lịch; không tự quy đổi
        return invalid(Reason.OUT_OF_RANGE)

    start = _affirmed_start(tokens)
    if start is None:
        return invalid(Reason.NEGATED)
    segment = tokens[start:]

    parsed = _parse_tokens(segment, today)
    if parsed is None:
        if (
            start > 0
            or _has_date_content(tokens)
            or find_last_phrase(joined, _AGE, mixed=True) is not None
        ):
            # Có nội dung ngày tháng nhưng không đọc ra vùng nào (tuổi thay ngày sinh, chữ số
            # lạc trong một câu khác) -> hỏi lại, và không ai được cắt tên dựa vào câu này
            return invalid(Reason.OUT_OF_RANGE)
        return Reading(Field.nothing(), Reason.NO_SIGNAL)

    # Từ đây đã có một vùng ngày có thật: các chốt chặn bên dưới vẫn trả vùng đó ra, để lượt
    # sau chỉ phải hỏi lại ngày sinh chứ không hỏi lại cả tên.
    value, lo, hi = parsed
    zone = " ".join(words[origin[start + lo][0] : origin[start + hi - 1][1] + 1])
    if (
        find_last_phrase(joined, UNCERTAINTY, mixed=True) is not None
        or english_hedge(text, date=True)
        or english_no(zone)
    ):
        # "14/3/1978 thì phải", "maybe March 14", "not 14/3/1978": người gọi đã tự nói là không
        # chắc hoặc bác bỏ — hỏi lại, đừng xác minh hộ
        return invalid(Reason.UNCERTAIN, zone)
    if _ambiguous(segment):
        return invalid(Reason.AMBIGUOUS, zone)
    if value is INVALID:
        return invalid(Reason.OUT_OF_RANGE, zone)
    return Reading(Field(value, provenance, span=text), Reason.OK, zone)


def _parse_stream(transcript: str) -> tuple[list[str], list[tuple[int, int]], bool]:
    """Token để phân tích, vị trí của chúng trong `clean(transcript)`, và có số tiếng Anh đọc bằng chữ không.

    "14/3/1978" được đọc thành "ngày 14 tháng 3 năm 1978" cho cùng một bộ luật, nhưng cả sáu
    token đều trỏ về ba từ có thật ("14", "3", "1978"), nên vùng ngày báo ra vẫn là lời người
    gọi thật sự nói.
    """
    tokens: list[str] = []
    origin: list[tuple[int, int]] = []
    index = 0
    for chunk in _TIGHTEN.sub(r"\1", normalize(transcript)).split():
        produced = strip_punctuation(chunk).split()
        if not produced:
            continue
        here = (index, index + len(produced) - 1)
        index += len(produced)
        match = _NUMERIC_DATE.fullmatch(chunk.strip(_TRIM))
        iso = _ISO_DATE.fullmatch(chunk.strip(_TRIM))
        if iso is not None:
            year, month, day = iso.groups()
        elif match is not None:
            day, month, year = match.groups()
        else:
            tokens += produced
            origin += [(i, i) for i in range(here[0], here[1] + 1)]
            continue
        parts = ["ngày", day, "tháng", month] + (["năm", year] if year else [])
        tokens += parts
        origin += [here] * len(parts)
    return _english_dates(tokens, origin)


def _english_dates(
    tokens: list[str], origin: list[tuple[int, int]]
) -> tuple[list[str], list[tuple[int, int]], bool]:
    """ "march 14 1978" / "the 14th of march 1978" -> "ngày 14 tháng 3 năm 1978", cùng ngữ pháp.

    Như dạng số, mọi token dựng ra trỏ về cả cụm có thật, nên vùng ngày vẫn là lời người gọi nói.
    Cờ cuối: có số đọc bằng chữ ("fourteenth", "nineteen seventy eight") -> `Provenance.NORMALIZED`.
    """
    out_tokens: list[str] = []
    out_origin: list[tuple[int, int]] = []
    spoken = False
    i = 0
    while i < len(tokens):
        found = _english_date_at(tokens, i)
        if found is None:
            year_words = _english_year_words_at(tokens, i)
            if year_words is not None:
                out_tokens.append(year_words[0])
                out_origin.append((origin[i][0], origin[i + year_words[1] - 1][1]))
                i += year_words[1]
                spoken = True
                continue
            out_tokens.append(tokens[i])
            out_origin.append(origin[i])
            i += 1
            continue
        (day, month, year), end = found
        parts = ["ngày", day, "tháng", str(month)] + (["năm", year] if year else [])
        out_tokens += parts
        out_origin += [(origin[i][0], origin[end - 1][1])] * len(parts)
        spoken = spoken or any(_is_english_number_word(t) for t in tokens[i:end])
        i = end
        # Từ số tiếng Anh dính ngay sau ngày là số lạc ("nineteen seventy eighth" = năm 1970 + "eighth",
        # "nineteen seventy eight two"): chuyển sang chữ số để hỏi lại như dạng số ("March 14, 1978 2"),
        # không bỏ qua rồi nhận năm cụt (12/10/2026).
        while i < len(tokens) and _is_english_number_word(tokens[i]) and tokens[i] not in _EN_ZERO:
            out_tokens.append(str(_english_number_word(tokens[i])))
            out_origin.append(origin[i])
            spoken = True
            i += 1
    return out_tokens, out_origin, spoken


def _english_number_word(token: str) -> int:
    if token in _EN_UNITS:
        return _EN_UNITS[token]
    return _EN_TENS[token] if token in _EN_TENS else _EN_ORDINALS[token]


def _is_english_number_word(token: str) -> bool:
    return token in _EN_UNITS or token in _EN_TENS or token in _EN_ORDINALS


def _english_date_at(
    tokens: list[str], i: int
) -> Optional[tuple[tuple[str, int, Optional[str]], int]]:
    """((ngày, tháng, năm), token sau cuối) khi tại `i` là ngày tiếng Anh; năm `None` khi thiếu.

    Thiếu năm chỉ nhận với tháng không trùng tiếng Việt không dấu: "may 5" có thể là "mấy 5".
    """

    def skip(at: int, *words: str) -> int:
        return at + 1 if at < len(tokens) and tokens[at] in words else at

    def partial(month: str) -> bool:
        return month != "may"

    # "march 14 1978", "march the 14th, 1978", "march fourteenth nineteen seventy eight", "april 15"
    if tokens[i] in EN_MONTHS:
        at = skip(i + 1, "the")
        day = _english_day_at(tokens, at)
        if day is not None:
            after_day = at + day[1]
            at = skip(after_day, "of", "in")
            year = _english_year_at(tokens, at)
            if year is not None:
                return (day[0], EN_MONTHS[tokens[i]], year[0]), at + year[1]
            if partial(tokens[i]):
                return (day[0], EN_MONTHS[tokens[i]], None), after_day
    # "14 march 1978", "the 14th of march, 1978", "the fourteenth of march nineteen seventy eight"
    at = skip(i, "the")
    day = _english_day_at(tokens, at)
    if day is None:
        return None
    month_at = skip(at + day[1], "of")
    if month_at >= len(tokens) or tokens[month_at] not in EN_MONTHS:
        return None
    at = skip(month_at + 1, "of", "in")
    year = _english_year_at(tokens, at)
    if year is None:
        if not partial(tokens[month_at]):
            return None
        return (day[0], EN_MONTHS[tokens[month_at]], None), month_at + 1
    return (day[0], EN_MONTHS[tokens[month_at]], year[0]), at + year[1]


def _english_day_at(tokens: list[str], at: int) -> Optional[tuple[str, int]]:
    """(ngày dạng chữ số, số token) tại `at`: "14", "14th", "fourteen", "fourteenth", "twenty first"."""
    if at >= len(tokens):
        return None
    token = tokens[at]
    match = _EN_DAY.fullmatch(token)
    if match is not None:
        day, used = int(match.group(1)), 1
    elif token in _EN_TENS:
        day, used = _EN_TENS[token], 1
        if at + 1 < len(tokens):
            unit = _EN_ORDINALS.get(tokens[at + 1], _EN_UNITS.get(tokens[at + 1]))
            if unit is not None and 1 <= unit <= 9:
                day, used = day + unit, 2
    elif token in _EN_ORDINALS:
        day, used = _EN_ORDINALS[token], 1
    elif token in _EN_UNITS and token not in _EN_ZERO:
        day, used = _EN_UNITS[token], 1
    else:
        return None
    return (str(day), used) if 1 <= day <= 31 else None


def _english_year_at(tokens: list[str], at: int) -> Optional[tuple[str, int]]:
    """(năm dạng chữ số, số token) tại `at`: "1978", "78", hoặc năm đọc bằng chữ (dài nhất trước).

    Năm bằng chữ nhận đủ 4 chữ số, hoặc 2 chữ số khi có ít nhất hai từ ("seventy eight"); một từ đơn
    ("nineteen") không phải năm.
    """
    if at >= len(tokens):
        return None
    if _EN_YEAR.fullmatch(tokens[at]):
        return tokens[at], 1
    for used in range(min(_EN_YEAR_MAX_WORDS, len(tokens) - at), 0, -1):
        value = _english_number(tokens[at : at + used])
        if value is None or _dangling_and(tokens, at + used):
            continue
        if 1000 <= value <= 9999:
            return str(value), used
        if used >= 2 and 10 <= value <= 99:
            return f"{value:02d}", used
    return None


def _english_year_words_at(tokens: list[str], at: int) -> Optional[tuple[str, int]]:
    """Năm 4 chữ số đọc bằng chữ đứng riêng (không trong một ngày tiếng Anh): "nineteen seventy eight".

    Chuyển sang chữ số để "or nineteen seventy nine" sau một ngày vẫn là giá trị thứ hai (`_ambiguous`).
    Không chuyển số nhỏ hơn: "twenty one" trong câu khác không phải năm.
    """
    if at >= len(tokens) or tokens[at] not in _EN_UNITS and tokens[at] not in _EN_TENS:
        return None
    for used in range(min(_EN_YEAR_MAX_WORDS, len(tokens) - at), 1, -1):
        value = _english_number(tokens[at : at + used])
        if value is not None and 1000 <= value <= 9999 and not _dangling_and(tokens, at + used):
            return str(value), used
    return None


def _dangling_and(tokens: list[str], end: int) -> bool:
    """Dãy số dừng ở "thousand" / "hundred" rồi tới "and" mà không có số tiếp ("two thousand and" hết
    câu): năm cụt, không nhận "two thousand" rồi bỏ qua "and"."""
    return tokens[end - 1] in ("thousand", "hundred") and end < len(tokens) and tokens[end] == "and"


def _english_number(tokens: list[str]) -> Optional[int]:
    """Giá trị của dãy từ số tiếng Anh, hoặc None nếu dãy không phải một số."""
    if not tokens:
        return None
    value = _english_structured(tokens)
    return value if value is not None else _english_paired_year(tokens)


def _english_structured(tokens: list[str]) -> Optional[int]:
    """ "two thousand (and) four", "nineteen hundred (and) seventy eight", "seventy eight", "fourteen"."""
    if "thousand" in tokens:
        at = tokens.index("thousand")
        high = _english_below_thousand(tokens[:at])
        if high is None or high == 0:
            return None
        rest = tokens[at + 1 :]
        if not rest:
            return high * 1000
        if rest[0] == "and":
            rest = rest[1:]
            if not rest:
                return None  # "two thousand and" cụt
        low = _english_below_thousand(rest)
        return None if low is None else high * 1000 + low
    return _english_below_thousand(tokens)


def _english_below_thousand(tokens: list[str]) -> Optional[int]:
    if "hundred" in tokens:
        at = tokens.index("hundred")
        if at != 1 or tokens[0] not in _EN_UNITS or tokens[0] in _EN_ZERO:
            return None
        rest = tokens[2:]
        if not rest:
            return _EN_UNITS[tokens[0]] * 100
        if rest[0] == "and":
            rest = rest[1:]
            if not rest:
                return None  # "nineteen hundred and" cụt
        low = _english_below_hundred(rest)
        return None if low is None else _EN_UNITS[tokens[0]] * 100 + low
    return _english_below_hundred(tokens)


def _english_below_hundred(tokens: list[str]) -> Optional[int]:
    """ "fourteen", "twenty", "seventy eight", "oh five" (chỉ sau một cặp thế kỷ)."""
    if len(tokens) == 1:
        token = tokens[0]
        if token in _EN_TENS:
            return _EN_TENS[token]
        if token in _EN_UNITS and token not in _EN_ZERO:
            return _EN_UNITS[token]
        return None
    if len(tokens) == 2:
        unit = _EN_UNITS.get(tokens[1])
        if unit is None or not 1 <= unit <= 9:
            return None
        if tokens[0] in _EN_TENS:
            return _EN_TENS[tokens[0]] + unit
        if tokens[0] in _EN_ZERO:
            return unit
    return None


def _english_paired_year(tokens: list[str]) -> Optional[int]:
    """ "nineteen seventy eight" = 19 | 78, "twenty twenty" = 20 | 20, "nineteen oh five" = 19 | 05.

    Cặp đầu là 19 hoặc 20; cặp sau là hai từ, hoặc một từ hàng chục ("nineteen ninety"). Một từ đơn vị
    ("twenty one") không nhận: có thể là 21.
    """
    if len(tokens) < 2 or tokens[0] not in _EN_UNITS and tokens[0] not in _EN_TENS:
        return None
    century = _english_below_hundred(tokens[:1])
    tail = tokens[1:]
    if century not in _EN_CENTURIES or len(tail) > 2:
        return None
    if len(tail) == 1 and tail[0] not in _EN_TENS and _EN_UNITS.get(tail[0], 0) < 10:
        return None  # "twenty ten" = 2010 nhận; "twenty one" không
    rest = _english_below_hundred(tail)
    return None if rest is None else century * 100 + rest


def _without_lead_ins(tokens: list[str]) -> list[int]:
    """Chỉ số các token còn lại sau khi bỏ cụm dẫn "ngày tháng năm sinh", "năm sinh", "sinh năm".

    Cụm dẫn không phải một phần của ngày: "tháng" trong "ngày tháng năm sinh" làm câu có hai
    "tháng", "năm" trong "năm sinh 14 3 1978" bị đọc thành số 5, và "sinh" chặn đứng
    "14 tháng 3 sinh năm 1978" trước phần năm. Riêng "sinh năm"/"năm sinh" đứng *sau* "tháng"
    là từ khoá năm của chính ngày đó -> giữ lại "năm", chỉ bỏ "sinh".
    """
    dropped: set[int] = set()
    for i in range(len(tokens) - 3):
        if tokens[i : i + 4] == ["ngày", "tháng", "năm", "sinh"]:
            dropped.update(range(i, i + 4))
    months = [i for i, t in enumerate(tokens) if t == "tháng" and i not in dropped]
    i = 0
    while i < len(tokens) - 1:
        if dropped.isdisjoint((i, i + 1)) and {tokens[i], tokens[i + 1]} == {"năm", "sinh"}:
            year, sinh = (i, i + 1) if tokens[i] == "năm" else (i + 1, i)
            dropped.add(sinh)
            if not any(m < i for m in months):
                dropped.add(year)
            i += 2
            continue
        i += 1
    return [i for i in range(len(tokens)) if i not in dropped]


def _affirmed_start(tokens: list[str]) -> Optional[int]:
    """Token bắt đầu mệnh đề được khẳng định sau cùng; `None` nếu câu chỉ bác bỏ.

    Cụm chỉ được tính khi ít nhất một bên có nội dung ngày tháng. Ở bước hỏi tên, một tên
    không dấu ("nguyen van a khong nho") khôi phục thành "... à không ..." — đó là tên cộng
    lời từ chối, không phải lời tự sửa ngày sinh.
    """
    text = " ".join(tokens)
    negation = find_last_phrase(text, NEGATIONS, mixed=True)
    correction = find_last_phrase(text, CORRECTIONS, mixed=True)
    marker = max(
        (m for m in (negation, correction) if m is not None), key=lambda m: m.end(), default=None
    )
    if marker is None:
        return 0
    before = token_index(tokens, marker.start())
    after = token_index(tokens, marker.end() - 1) + 1
    if not _has_date_content(tokens[:before]) and not _has_date_content(tokens[after:]):
        return 0
    if marker is not negation:
        return after
    # "không phải A" -> không còn giá trị nào; chỉ "mà là B" mới đưa ra giá trị thay thế
    tail = tokens[after:]
    affirmation = find_phrase(" ".join(tail), AFFIRMATIONS, mixed=True)
    if affirmation is None:
        return None
    return after + token_index(tail, affirmation.end() - 1) + 1


def _ambiguous(tokens: list[str]) -> bool:
    """ "14 hay 15 tháng 3", "... năm 1978 hoặc 1979": hai cách đọc, không chọn hộ.

    Chỉ tính khi hai bên của từ nối đều là số (bên sau có thể là tên tháng tiếng Anh) — "hay" ở chỗ
    khác trong câu không phải lựa chọn giữa hai ngày.
    """
    if tokens.count("tháng") > 1:
        return True
    text = " ".join(tokens)
    for _, pattern in ALTERNATIVES.for_text(text, mixed=True):
        for match in pattern.finditer(text):
            before = token_index(tokens, match.start())
            after = token_index(tokens, match.end() - 1) + 1
            if after < len(tokens) and tokens[after] == "ngày":
                after += 1  # Numeric dates expand to "ngày 15 tháng ...".
            if before > 0 and after < len(tokens):
                # "March 14, 1978 or May 15": tên tháng tiếng Anh sau từ nối cũng là giá trị thứ hai
                second = is_number_token(tokens[after]) or tokens[after] in EN_MONTHS
                if is_number_token(tokens[before - 1]) and second:
                    return True
    return False


def _uses_spoken_numbers(tokens: list[str]) -> bool:
    """Có số đọc bằng chữ không. "năm" đứng trước một số là từ khoá năm, không phải số 5."""
    return any(
        is_number_token(t)
        and not t.isdigit()
        and not (t == "năm" and i + 1 < len(tokens) and tokens[i + 1].isdigit())
        for i, t in enumerate(tokens)
    )


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


def _parse_tokens(tokens: list[str], today: date) -> Optional[tuple[DobValue, int, int]]:
    """(giá trị, token đầu, token sau cuối) của vùng ngày; `None` khi không có nội dung ngày tháng.

    Vùng được trả về cả khi giá trị là `INVALID`: "31/02/1978" vẫn là một vùng ngày có thật,
    nên phần còn lại của câu vẫn tách được thành tên. Câu chỉ tình cờ có chữ số ("chi trả 80%")
    thì không có vùng nào — không được cắt tên ở đó.
    """
    months = [i for i, t in enumerate(tokens) if t == "tháng"]
    if len(months) > 1:
        return (INVALID, *_date_extent(tokens))
    if months:
        return _parse_with_month_anchor(tokens, months[0], today)
    return _parse_digit_sequence(tokens, today)


def _date_extent(tokens: list[str]) -> tuple[int, int]:
    at = [i for i, t in enumerate(tokens) if is_number_token(t) or t in _DATE_WORDS]
    return (at[0], at[-1] + 1) if at else (0, len(tokens))


def _parse_with_month_anchor(tokens: list[str], at: int, today: date) -> tuple[DobValue, int, int]:
    day_tokens = _number_run_before(tokens, at)
    day = parse_spoken_number(day_tokens) if day_tokens else None
    lo = at - len(day_tokens)
    if day is None or not 1 <= day <= 31:
        return INVALID, lo, at + 1

    after = _number_run_after(tokens, at + 1)
    hi = at + 1 + len(after)
    candidates: set[date] = set()
    saw_invalid = False
    for split in range(1, min(len(after), 3) + 1):
        month = parse_spoken_number(after[:split])
        if month is None or not 1 <= month <= 12:
            continue
        rest = after[split:]
        year_tokens: Optional[list[str]] = None
        if len(rest) > 1 and rest[0] == "năm":
            year_tokens = rest[1:]
        elif len(rest) == 1 and rest[0].isdigit():
            year_tokens = rest  # "14 tháng 3 1978"
        elif rest and _is_full_year(rest):
            # "mười bảy tháng tám một chín sáu tám": thiếu "năm" thì chỉ nhận năm đủ 4 chữ số,
            # để "tháng mười một" không bị tách thành tháng 10 năm "một"
            year_tokens = rest
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
        return candidates.pop(), lo, hi
    return INVALID, lo, hi


def _parse_digit_sequence(tokens: list[str], today: date) -> Optional[tuple[DobValue, int, int]]:
    """Không có "tháng": "14 3 1978", "14031978", "một bốn không ba một chín bảy tám"."""
    picked = [i for i, t in enumerate(tokens) if t not in _FILLERS or is_number_token(t)]
    content = [tokens[i] for i in picked]
    if not content or not all(is_number_token(t) for t in content):
        return None
    if len(content) == 1 and not content[0].isdigit():
        return None  # một từ số đứng một mình ("không") — không phải câu trả lời ngày sinh
    lo, hi = picked[0], picked[-1] + 1

    if len(content) == 3 and all(t.isdigit() for t in content):
        value = _resolve_date(int(content[0]), int(content[1]), [content[2]], today) or INVALID
        return value, lo, hi
    digits = spoken_digits(content)
    if digits is None or len(digits) not in (6, 8):
        return INVALID, lo, hi
    value = _resolve_date(int(digits[:2]), int(digits[2:4]), [digits[4:]], today) or INVALID
    return value, lo, hi


def _resolve_date(day: int, month: int, year_tokens: list[str], today: date) -> Optional[DobValue]:
    """None: dãy token không đọc được thành năm. INVALID: đọc được nhưng ngày không hợp lệ / mơ hồ."""
    if all(t.isdigit() for t in year_tokens):
        raw = "".join(year_tokens)
        if len(raw) == 2:
            return _resolve_two_digit_year(day, month, int(raw), today)
        if len(raw) != 4:
            return INVALID
        return _checked(day, month, int(raw), today)

    year = parse_spoken_number(year_tokens)
    if year is None:
        return None
    if year < 100:
        return _resolve_two_digit_year(day, month, year, today)
    if year < 1000:
        return INVALID
    return _checked(day, month, year, today)


def _is_full_year(tokens: list[str]) -> bool:
    """Năm đủ 4 chữ số khi không có từ khoá "năm" đứng trước.

    "năm" đứng trước một số là từ khoá năm của một cách tách khác ("tháng mười | hai năm tám
    lăm") — không được đọc nó thành chữ số 5; "năm" ở cuối ("một chín tám năm") vẫn là số.
    """
    if any(t == "năm" and is_number_token(n) for t, n in zip(tokens, tokens[1:], strict=False)):
        return False
    year = parse_spoken_number(tokens)
    return year is not None and 1000 <= year <= 9999


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
