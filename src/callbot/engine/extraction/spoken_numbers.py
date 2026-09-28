"""Đọc số nói tiếng Việt: "mười bốn", "hai mươi mốt", "một nghìn chín trăm bảy mươi tám",
"một chín bảy tám" (đọc rời), "bảy tám" (năm 2 chữ số).

Chỉ phục vụ ngày sinh và giờ slot. Đầu vào là danh sách token đã qua `text.clean`.
"""

from typing import Optional, Sequence

DIGIT_WORDS: dict[str, int] = {
    "không": 0,
    "linh": 0,
    "một": 1,
    "mốt": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "tư": 4,
    "năm": 5,
    "lăm": 5,
    "nhăm": 5,
    "sáu": 6,
    "bảy": 7,
    "bẩy": 7,
    "tám": 8,
    "chín": 9,
}
_TENS_WORDS = frozenset({"mươi", "mười"})
_ZERO_TENS = frozenset({"linh", "lẻ"})
_HUNDRED = "trăm"
_THOUSAND = frozenset({"nghìn", "ngàn"})
# "mốt", "lăm", "tư" là biến âm chỉ đứng sau hàng chục; "linh" chỉ đứng sau hàng trăm.
_TRAILING_ONLY = frozenset({"mốt", "lăm", "nhăm", "linh"})

NUMBER_WORDS = frozenset(DIGIT_WORDS) | _TENS_WORDS | _ZERO_TENS | {_HUNDRED} | _THOUSAND

# Transcript không dấu. "muoi", "mot" cần ngữ cảnh; "sau" (sáu/sau), "tu" (tư/từ), "lam" (lăm/làm)
# trùng từ thường nên chỉ bên gọi (ngày sinh, giờ slot) mới quyết định có khôi phục hay không.
_UNACCENTED_NUMBER_WORDS = {
    "khong": "không",
    "hai": "hai",
    "ba": "ba",
    "bon": "bốn",
    "nam": "năm",
    "bay": "bảy",
    "tam": "tám",
    "chin": "chín",
    "linh": "linh",
    "le": "lẻ",
    "tram": "trăm",
    "nghin": "nghìn",
    "ngan": "ngàn",
}
_UNITS_BEFORE_TENS = frozenset({"hai", "ba", "bốn", "tư", "năm", "sáu", "bảy", "tám", "chín"})


def restore_number_words(
    tokens: Sequence[str], extra: Optional[dict[str, str]] = None
) -> list[str]:
    """Khôi phục dấu cho từ số trong transcript không dấu: "hai muoi mot" -> "hai mươi mốt".

    `extra`: bảng từ riêng của bên gọi, áp dụng trước bảng số.
    """
    extra = extra or {}
    restored: list[str] = []
    for token in tokens:
        previous = restored[-1] if restored else None
        if token in extra:
            restored.append(extra[token])
        elif token == "muoi":
            restored.append("mươi" if previous in _UNITS_BEFORE_TENS else "mười")
        elif token == "mot":
            restored.append("mốt" if previous == "mươi" else "một")
        else:
            restored.append(_UNACCENTED_NUMBER_WORDS.get(token, token))
    return restored


def is_number_token(token: str) -> bool:
    return token.isdigit() or token in NUMBER_WORDS


def spoken_digits(tokens: Sequence[str]) -> Optional[str]:
    """Đọc rời từng chữ số: ["một", "bốn", "không", "ba"] -> "1403". Giữ số 0 đứng đầu."""
    if not tokens:
        return None
    digits = []
    for token in tokens:
        if token.isdigit():
            digits.append(token)
        elif token in DIGIT_WORDS and token != "linh":
            digits.append(str(DIGIT_WORDS[token]))
        else:
            return None
    return "".join(digits)


def parse_number(tokens: Sequence[str]) -> Optional[int]:
    """Giá trị số của cả dãy token, hoặc None nếu dãy không phải một số hợp lệ."""
    tokens = list(tokens)
    if not tokens:
        return None
    if all(t.isdigit() for t in tokens):
        return int("".join(tokens))
    if any(t.isdigit() for t in tokens):
        return None
    if not any(
        t in _TENS_WORDS or t in _ZERO_TENS or t == _HUNDRED or t in _THOUSAND for t in tokens
    ):
        # Toàn chữ số đơn: đọc rời ("một chín bảy tám") hoặc nói tắt ("hai mốt" = 21)
        if len(tokens) > 1 and tokens[0] in _TRAILING_ONLY:
            return None
        digits = spoken_digits(tokens)
        return int(digits) if digits is not None else None
    return _parse_structured(tokens)


_DIGIT_AS_WORD = dict(
    zip(
        "0123456789",
        ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"),
        strict=True,
    )
)


def parse_spoken_number(tokens: Sequence[str]) -> Optional[int]:
    """`parse_number` thêm hai dạng ASR hay ra khi người gọi đọc ngày sinh.

    - Chữ số lẫn với từ số: "2 không linh tư", "2 nghìn linh 4", "mười 4" — chữ số đơn được đọc
      lại thành từ rồi phân tích như câu nói.
    - "linh" / "lẻ" thay "không" khi đọc rời từng chữ số: "hai không linh tư" = 2004. Chỉ nhận
      khi đứng giữa hai chữ số: "linh tư" đứng một mình vẫn không đọc ra được.

    Chỉ dùng cho ngày sinh: ở giờ slot, "thứ 2 ba giờ" không được thành 23.
    """
    tokens = list(tokens)
    if any(not t.isdigit() for t in tokens):
        if any(t.isdigit() and t not in _DIGIT_AS_WORD for t in tokens):
            return None  # "mười 14": chữ số nhiều chữ lẫn với từ -> không đoán
        tokens = [_DIGIT_AS_WORD.get(t, t) for t in tokens]
    value = parse_number(tokens)
    if value is not None:
        return value
    inner = tokens[1:-1]
    if (
        len(tokens) >= 3
        and tokens[0] in DIGIT_WORDS
        and tokens[0] not in _TRAILING_ONLY
        and tokens[-1] in DIGIT_WORDS
        and tokens[-1] not in _ZERO_TENS
        and any(t in _ZERO_TENS for t in inner)
        and all(t in DIGIT_WORDS or t in _ZERO_TENS for t in inner)
    ):
        digits = spoken_digits(["không" if t in _ZERO_TENS else t for t in tokens])
        return int(digits) if digits is not None else None
    return None


def _parse_structured(tokens: list[str]) -> Optional[int]:
    thousand_at = next((i for i, t in enumerate(tokens) if t in _THOUSAND), None)
    if thousand_at is not None:
        head = tokens[:thousand_at]
        high = _below_thousand(head) if head else 1
        low = (
            _below_thousand(tokens[thousand_at + 1 :], after_scale=True)
            if tokens[thousand_at + 1 :]
            else 0
        )
        if high is None or low is None or high == 0:
            return None
        return high * 1000 + low
    return _below_thousand(tokens)


def _below_thousand(tokens: list[str], after_scale: bool = False) -> Optional[int]:
    if _HUNDRED in tokens:
        at = tokens.index(_HUNDRED)
        if at != 1 or tokens[0] not in DIGIT_WORDS or tokens[0] in _TRAILING_ONLY:
            return None
        rest = _below_hundred(tokens[2:], after_hundred=True)
        return None if rest is None else DIGIT_WORDS[tokens[0]] * 100 + rest
    if after_scale and tokens and tokens[0] in _ZERO_TENS:
        # "hai nghìn linh năm" = 2005
        return _below_hundred(tokens, after_hundred=True)
    return _below_hundred(tokens, after_hundred=False)


def _below_hundred(tokens: list[str], after_hundred: bool) -> Optional[int]:
    n = len(tokens)
    if n == 0:
        return 0
    if tokens[0] in _ZERO_TENS:
        if after_hundred and n == 2 and _unit(tokens[1], allow_trailing=True) not in (None, 0):
            return _unit(tokens[1], allow_trailing=True)
        return None
    if tokens[0] == "mười":
        if n == 1:
            return 10
        if n == 2:
            unit = _unit(tokens[1], allow_trailing=True, after_ten=True)
            return None if unit in (None, 0) else 10 + unit
        return None
    first = _unit(tokens[0])
    if first is None:
        return None
    if n == 1:
        return first
    if tokens[1] == "mươi":
        if first < 2 or n > 3:
            return None
        if n == 2:
            return first * 10
        unit = _unit(tokens[2], allow_trailing=True)
        return None if unit in (None, 0) else first * 10 + unit
    if n == 2:
        # Nói tắt "hai mốt", "ba lăm"
        unit = _unit(tokens[1], allow_trailing=True)
        return None if unit is None or first == 0 else first * 10 + unit
    return None


def _unit(token: str, allow_trailing: bool = False, after_ten: bool = False) -> Optional[int]:
    if token not in DIGIT_WORDS or token == "linh":
        return None
    if token in _TRAILING_ONLY and not allow_trailing:
        return None
    if token == "mốt" and after_ten:
        return None  # "mười một", không nói "mười mốt"
    return DIGIT_WORDS[token]
