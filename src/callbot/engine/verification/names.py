"""Khoá so khớp tên cho Verifier (chuyển từ `engine/nlu/normalizer.py`, giữ nguyên quy tắc)."""

import unicodedata


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
