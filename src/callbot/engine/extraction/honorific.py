"""Danh xưng người gọi tự đặt trước tên: "tôi là ÔNG Nguyễn Văn A", "bà Lê Na".

Danh xưng không thuộc họ tên trong hồ sơ, nên giữ nó thì Verifier so "ong nguyen van a" với
"nguyen van a" và chuyển máy nhầm IDENTITY_FAILED. Nhưng một số từ cũng là HỌ thật ("Chu", "Ông"
Văn Tùng), nên chỉ bỏ khi phần còn lại vẫn đủ dài để là một họ tên (`min_rest`).
"""

from callbot.engine.extraction.text import strip_diacritics

_HONORIFICS = frozenset({"ông", "bà", "anh", "chị", "cô", "chú", "bác", "cháu", "em"})

_HONORIFICS_UNACCENTED = frozenset(strip_diacritics(w) for w in _HONORIFICS) - {"chu"}


def is_honorific(word: str) -> bool:
    word = word.lower()
    return word in _HONORIFICS or word in _HONORIFICS_UNACCENTED


def strip_honorific(name: str, min_rest: int) -> str:
    """Bỏ MỘT danh xưng ở đầu nếu sau đó còn ít nhất `min_rest` từ; ngược lại giữ nguyên."""
    words = name.split()
    if len(words) - 1 < min_rest:
        return name
    if is_honorific(words[0]):
        return " ".join(words[1:])
    return name
