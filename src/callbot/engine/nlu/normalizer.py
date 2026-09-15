"""Chuẩn hoá & kiểm tra dữ liệu trích xuất (tên, ngày tháng)."""

import re
import unicodedata
from datetime import date
from typing import Optional

_DOB_WORDS = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})")
_DOB_NUMERIC = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_name(name: str) -> str:
    """Khoá so khớp tên: bỏ dấu, lowercase, gộp khoảng trắng.

    Bỏ dấu để chịu được lỗi ASR; đánh đổi là "Hà" khớp "Hạ" — DOB là yếu tố thứ hai.
    """
    return " ".join(strip_diacritics(normalize_text(name)).split())


def parse_dob(text: str) -> Optional[date]:
    """TODO: số đọc bằng chữ từ ASR ("mười bốn tháng ba..."), năm 2 chữ số."""
    normalized = normalize_text(text)
    match = _DOB_WORDS.search(normalized) or _DOB_NUMERIC.search(normalized)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if not (1900 <= parsed.year <= date.today().year):
        return None
    return parsed
