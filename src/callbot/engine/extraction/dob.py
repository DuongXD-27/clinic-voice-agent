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
# Người gọi nói tiếng Anh (QC qc-w6-01): "March 14, 1978", "14th of March 1978". Chỉ nhận khi đủ
# ngày, tháng và năm viết bằng chữ số; số đọc bằng chữ tiếng Anh ("nineteen seventy eight") chưa hỗ trợ.
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
    spoken, origin = _parse_stream(transcript)
    tokens = restore_number_words(spoken, _UNACCENTED_WORDS)
    keep = _without_lead_ins(tokens)
    spoken = [spoken[i] for i in keep]
    origin = [origin[i] for i in keep]
    tokens = [tokens[i] for i in keep]
    provenance = (
        Provenance.NORMALIZED
        if tokens != spoken or _uses_spoken_numbers(tokens)
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
    if find_last_phrase(joined, UNCERTAINTY, mixed=True) is not None:
        # "14/3/1978 thì phải": người gọi đã tự nói là không chắc — hỏi lại, đừng xác minh hộ
        return invalid(Reason.UNCERTAIN, zone)
    if _ambiguous(segment):
        return invalid(Reason.AMBIGUOUS, zone)
    if value is INVALID:
        return invalid(Reason.OUT_OF_RANGE, zone)
    return Reading(Field(value, provenance, span=text), Reason.OK, zone)


def _parse_stream(transcript: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Token để phân tích, kèm vị trí của chúng trong `clean(transcript)`.

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
) -> tuple[list[str], list[tuple[int, int]]]:
    """ "march 14 1978" / "the 14th of march 1978" -> "ngày 14 tháng 3 năm 1978", cùng ngữ pháp.

    Như dạng số, mọi token dựng ra trỏ về cả cụm có thật, nên vùng ngày vẫn là lời người gọi nói.
    """
    out_tokens: list[str] = []
    out_origin: list[tuple[int, int]] = []
    i = 0
    while i < len(tokens):
        found = _english_date_at(tokens, i)
        if found is None:
            out_tokens.append(tokens[i])
            out_origin.append(origin[i])
            i += 1
            continue
        (day, month, year), end = found
        parts = ["ngày", day, "tháng", str(month), "năm", year]
        out_tokens += parts
        out_origin += [(origin[i][0], origin[end - 1][1])] * len(parts)
        i = end
    return out_tokens, out_origin


def _english_date_at(tokens: list[str], i: int) -> Optional[tuple[tuple[str, int, str], int]]:
    """((ngày, tháng, năm), token sau cuối) khi tại `i` là ngày tiếng Anh đủ ba phần."""

    def skip(at: int, *words: str) -> int:
        return at + 1 if at < len(tokens) and tokens[at] in words else at

    def day_at(at: int) -> Optional[str]:
        match = _EN_DAY.fullmatch(tokens[at]) if at < len(tokens) else None
        return match.group(1) if match else None

    def year_at(at: int) -> Optional[str]:
        return tokens[at] if at < len(tokens) and _EN_YEAR.fullmatch(tokens[at]) else None

    # "march 14 1978", "march the 14th, 1978"
    if tokens[i] in EN_MONTHS:
        at = skip(i + 1, "the")
        day = day_at(at)
        at = skip(at + 1, "of", "in")
        year = year_at(at)
        if day is not None and year is not None:
            return (day, EN_MONTHS[tokens[i]], year), at + 1
    # "14 march 1978", "the 14th of march, 1978"
    at = skip(i, "the")
    day = day_at(at)
    if day is None:
        return None
    month_at = skip(at + 1, "of")
    if month_at >= len(tokens) or tokens[month_at] not in EN_MONTHS:
        return None
    at = skip(month_at + 1, "of", "in")
    year = year_at(at)
    if year is None:
        return None
    return (day, EN_MONTHS[tokens[month_at]], year), at + 1


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

    Chỉ tính khi hai bên của từ nối đều là số — "hay" ở chỗ khác trong câu không phải lựa
    chọn giữa hai ngày.
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
                if is_number_token(tokens[before - 1]) and is_number_token(tokens[after]):
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
