"""R-22: so từng âm tiết, giữ nguyên dấu; lệch dấu thanh cần hỏi lại khi N chưa chốt.

Ngoại lệ (QC qc-stt-05, qc-w6-01): tên khai không có dấu nào ("nguyen van a" — ASR mất dấu, người
gõ / nói không dấu) không mang thông tin dấu để so, nên so trên bản bỏ hết dấu. Ngày sinh vẫn so
tuyệt đối. Tên có dấu một phần vẫn theo luật chặt: đã có dấu mà khác hồ sơ là bằng chứng khác tên.
"""

import unicodedata
from enum import Enum

from callbot.engine.extraction.text import is_unaccented, normalize


class NameMatch(str, Enum):
    MATCH = "MATCH"
    SUSPICIOUS = "SUSPICIOUS"
    MISMATCH = "MISMATCH"


_TONES = frozenset("\u0300\u0301\u0303\u0309\u0323")


def strip_tones(text: str) -> str:
    """Remove tone marks only: ă/â/ê/ô/ơ/ư/đ remain distinct syllables."""
    return unicodedata.normalize(
        "NFC", "".join(c for c in unicodedata.normalize("NFD", text) if c not in _TONES)
    )


def compare_names(claimed: str, reference: str) -> NameMatch:
    left, right = normalize_name(claimed).split(), normalize_name(reference).split()
    if not left or len(left) != len(right):
        return NameMatch.MISMATCH
    if left == right:
        return NameMatch.MATCH
    if is_unaccented(" ".join(left)) and left == [strip_diacritics(s) for s in right]:
        return NameMatch.MATCH
    if [strip_tones(s) for s in left] == [strip_tones(s) for s in right]:
        # N is not calibrated: a tone difference never authenticates a caller.
        return NameMatch.SUSPICIOUS
    return NameMatch.MISMATCH


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_name(name: str) -> str:
    """Canonical spelling, retaining vowels, consonants and tone marks (R-22)."""
    return normalize(name)
