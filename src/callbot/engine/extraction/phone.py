"""Số điện thoại người gọi tự đọc — chỉ ở ASK_PHONE (inbound không có `caller_number`).

Số chỉ để tra `GET /patients?phone=`, không phải bằng chứng danh tính (§1.1.9): xác minh vẫn là họ tên
+ ngày sinh đã khai trước đó. Ở đây chỉ nhận dãy chữ số — viết số ("0912 345 600", "84912345600") hoặc
đọc rời ("không chín một hai ba bốn năm sáu không không") — và trả nguyên dãy chữ số. Chuẩn hóa đầu số
("0", "+84", "84") về dạng mock nhận thuộc Verifier (`verification.phone.normalize_phone`, cùng hàm
với `caller_number`); không chuẩn hóa được thì Dialogue hỏi lại — không đoán chữ số.

Tự sửa (PRD R-44): "0912345601, à không, 0912345600" — lấy dãy số nói SAU CÙNG. "không" vừa là chữ số
0 vừa nằm trong lời sửa ("à không"), nên trước hết tách câu tại lời sửa; đoạn sau không ra dãy đủ dài
thì đọc cả câu ("à, không chín một hai..." là người gọi bắt đầu đọc số).
"""

from typing import Optional

from callbot.engine.extraction.identity import CORRECTIONS
from callbot.engine.extraction.schema import Field, Provenance
from callbot.engine.extraction.spoken_numbers import DIGIT_WORDS, restore_number_words
from callbot.engine.extraction.text import clean

# 10 chữ số nội địa ("09..."), 11 với "84...", 12 với "840..." — Verifier chuẩn hóa tiếp
PHONE_DIGIT_LENGTHS = frozenset({10, 11, 12})
# Không dấu: "sau" / "tu" / "le" ở câu đọc số chỉ có thể là chữ số
_UNACCENTED_DIGITS = {"sau": "sáu", "tu": "tư", "le": "lẻ"}
# Lời đệm được phép xen giữa các nhóm số ("không chín một hai, ba bốn năm, sáu không không ạ")
_FILLERS = frozenset({"ạ", "à", "ờ", "ừ", "dạ", "vâng", "là", "nhé", "nha", "số", "rồi"})
# "hai mươi mốt" đọc theo hàng chục: hàng chục đứng giữa hai chữ số thì bỏ, đứng cuối là số 0
_TENS = frozenset({"mươi", "mười"})
_DIGITS = frozenset(DIGIT_WORDS) | {"lẻ"}


def extract_phone(transcript: str) -> Field[str]:
    text = clean(transcript)
    if not text:
        return Field.nothing()
    for candidates in (_split_corrections(text), [text]):
        for segment in reversed(candidates):
            digits = _last_phone_run(segment)
            if digits is not None:
                exact = all(token.isdigit() for token in segment.split())
                provenance = Provenance.EXACT if exact else Provenance.NORMALIZED
                return Field(digits, provenance, span=text)
    return Field.nothing()


def _split_corrections(text: str) -> list[str]:
    cuts = sorted(
        (match.start(), match.end())
        for _, pattern in CORRECTIONS.for_text(text, mixed=True)
        for match in pattern.finditer(text)
    )
    segments, at = [], 0
    for start, end in cuts:
        if start >= at:
            segments.append(text[at:start])
            at = end
    return [*segments, text[at:]]


def _last_phone_run(text: str) -> Optional[str]:
    """Dãy chữ số sau cùng có độ dài của một số điện thoại; lời đệm giữa các nhóm số không cắt dãy."""
    runs: list[list[str]] = [[]]
    for token in restore_number_words(text.split(), _UNACCENTED_DIGITS):
        if token.isdigit() or token in _DIGITS or token in _TENS:
            runs[-1].append(token)
        elif token not in _FILLERS and runs[-1]:
            runs.append([])
    for run in reversed(runs):
        digits = _digits(run)
        if digits is not None and len(digits) in PHONE_DIGIT_LENGTHS:
            return digits
    return None


def _digits(run: list[str]) -> Optional[str]:
    digits: list[str] = []
    for index, token in enumerate(run):
        if token.isdigit():
            digits.append(token)
        elif token in _TENS:
            if token == "mười":
                digits.append("1")
            follows_unit = index + 1 < len(run) and run[index + 1] not in _TENS
            if not follows_unit:
                digits.append("0")
        elif token == "lẻ":
            digits.append("0")
        elif token in DIGIT_WORDS:
            digits.append(str(DIGIT_WORDS[token]))
        else:
            return None
    return "".join(digits) if digits else None


__all__ = ["PHONE_DIGIT_LENGTHS", "extract_phone"]
