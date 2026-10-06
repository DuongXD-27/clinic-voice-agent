"""Chuẩn hoá văn bản tiếng Việt và so khớp cụm từ theo ranh giới từ.

Mọi bộ trích xuất và mọi danh sách từ khoá đi qua cùng một hàm `normalize`, nên
"huỷ" / "hủy", "hoà" / "hòa" khớp nhau bất kể người gõ hay ASR dùng kiểu bỏ dấu nào.

Transcript KHÔNG DẤU (ASR mất dấu ở audio mode, §4.1): nếu cả câu không có ký tự nào mang dấu,
`find_phrase` so với bản không dấu của từ khoá. Bỏ dấu làm nhiều từ trùng nhau ("dạ"/"đã",
"đúng"/"đừng", "từ từ"/"tự tử"), nên mỗi danh sách từ khoá tự khai báo cụm nào KHÔNG được
dùng ở chế độ không dấu (`unaccented_exclude`). Câu có dấu một phần thì vẫn so có dấu.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

# Kiểu bỏ dấu mới (hoà, huỷ) -> kiểu cũ (hòa, hủy), chỉ ở âm tiết mở.
# Âm tiết đóng (hoàng, thuyết) chỉ có một cách viết nên không đụng tới.
# "quý": u thuộc phụ âm "qu" nên dấu luôn nằm trên y — loại trừ bằng (?<!q).
_TONE_PLACEMENT = {
    "oà": "òa",
    "oá": "óa",
    "oả": "ỏa",
    "oã": "õa",
    "oạ": "ọa",
    "oè": "òe",
    "oé": "óe",
    "oẻ": "ỏe",
    "oẽ": "õe",
    "oẹ": "ọe",
    "uỳ": "ùy",
    "uý": "úy",
    "uỷ": "ủy",
    "uỹ": "ũy",
    "uỵ": "ụy",
}
_TONE_PLACEMENT_RE = re.compile(r"(?<!q)(" + "|".join(_TONE_PLACEMENT) + r")(?!\w)")
_PUNCTUATION_RE = re.compile(r"[^\w\s]|_")
_NEGATORS = frozenset({"không", "đừng", "chưa", "chẳng", "chả", "khỏi", "khoan"})
_NEGATION_MODALS = frozenset({"muốn", "cần", "phải", "định", "nên", "được"})
# Không dấu: "dung" có thể là "đừng" hoặc "đúng" — coi là phủ định, vì phủ định chỉ làm MẤT nhãn hành động
_NEGATORS_UNACCENTED = frozenset({"khong", "dung", "chua", "chang", "cha", "khoi", "khoan"})
_NEGATION_MODALS_UNACCENTED = frozenset({"muon", "can", "phai", "dinh", "nen", "duoc"})


def normalize(text: str) -> str:
    """NFC, lowercase, thống nhất vị trí dấu thanh, gộp khoảng trắng. Giữ dấu câu."""
    text = unicodedata.normalize("NFC", text).lower()
    text = _TONE_PLACEMENT_RE.sub(lambda m: _TONE_PLACEMENT[m.group(1)], text)
    return " ".join(text.split())


def strip_punctuation(text: str) -> str:
    """Thay dấu câu bằng khoảng trắng rồi gộp khoảng trắng. Đầu vào đã qua `normalize`."""
    return " ".join(_PUNCTUATION_RE.sub(" ", text).split())


def clean(text: str) -> str:
    """Dạng dùng cho so khớp từ khoá: `normalize` + bỏ dấu câu."""
    return strip_punctuation(normalize(text))


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return unicodedata.normalize(
        "NFC", "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    )


def is_unaccented(text: str) -> bool:
    """Có chữ cái nhưng không có ký tự mang dấu nào — dấu hiệu ASR trả văn bản không dấu."""
    return any(c.isalpha() for c in text) and strip_diacritics(text) == text


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    words = clean(phrase).split()
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)")


CompiledPhrases = tuple[tuple[str, re.Pattern[str]], ...]


@dataclass(frozen=True)
class PhraseSet:
    accented: CompiledPhrases
    unaccented: CompiledPhrases
    both: CompiledPhrases

    def for_text(
        self, text: str, unaccented: Optional[bool] = None, *, mixed: bool = False
    ) -> CompiledPhrases:
        """`unaccented=None`: tự nhận biết từ `text`. Truyền giá trị khi `text` là phần còn lại của câu gốc.

        `mixed=True`: so từng cụm theo cả hai dạng, cho transcript mà ASR chỉ bỏ dấu một phần
        ("Dạ toi la Nguyen Van A"). An toàn vì mẫu không dấu chỉ khớp được đúng chuỗi ký tự
        không dấu; các cụm nguy hiểm khi mất dấu vẫn bị `unaccented_exclude` loại khỏi tập này.
        """
        if mixed:
            return self.both
        if unaccented is None:
            unaccented = is_unaccented(text)
        return self.unaccented if unaccented else self.accented


def compile_phrases(phrases: Iterable[str], unaccented_exclude: Iterable[str] = ()) -> PhraseSet:
    """Cụm dài xếp trước để span trả về là cụm cụ thể nhất ("không hủy nữa" trước "không hủy").

    `unaccented_exclude`: cụm mà bản không dấu trùng với từ khác nghĩa — không dùng khi transcript không dấu.
    """
    accented = {clean(p) for p in phrases}
    excluded = {clean(p) for p in unaccented_exclude}
    unknown = excluded - accented
    if unknown:
        raise ValueError(f"unaccented_exclude không có trong danh sách: {sorted(unknown)}")
    unaccented = {strip_diacritics(p) for p in accented - excluded}
    return PhraseSet(_compile(accented), _compile(unaccented), _compile(accented | unaccented))


def _compile(phrases: set[str]) -> CompiledPhrases:
    ordered = sorted(phrases, key=lambda p: (-len(p.split()), p))
    return tuple((p, phrase_pattern(p)) for p in ordered)


def find_phrase(
    text: str,
    phrases: PhraseSet,
    *,
    allow_negated: bool = True,
    unaccented: Optional[bool] = None,
    mixed: bool = False,
) -> Optional[re.Match[str]]:
    """Trả về lần khớp đầu tiên của cụm dài nhất. `text` phải đã qua `clean`.

    Với `allow_negated=False`, cụm bị phủ định che luôn các cụm ngắn hơn nằm trong nó:
    "không cần gặp nhân viên" loại "gặp nhân viên" thì "nhân viên" cũng không được tính.
    """
    negated: list[tuple[int, int]] = []
    for _, pattern in phrases.for_text(text, unaccented, mixed=mixed):
        for match in pattern.finditer(text):
            if allow_negated:
                return match
            if any(start <= match.start() and match.end() <= end for start, end in negated):
                continue
            if is_negated(text, match.start(), unaccented):
                negated.append(match.span())
                continue
            return match
    return None


def find_last_phrase(
    text: str, phrases: PhraseSet, unaccented: Optional[bool] = None, *, mixed: bool = False
) -> Optional[re.Match[str]]:
    matches = [
        m
        for _, pattern in phrases.for_text(text, unaccented, mixed=mixed)
        for m in pattern.finditer(text)
    ]
    return max(matches, key=lambda m: m.end()) if matches else None


def remove_phrases(text: str, phrases: PhraseSet, unaccented: Optional[bool] = None) -> str:
    for _, pattern in phrases.for_text(text, unaccented):
        text = pattern.sub(" ", text)
    return " ".join(text.split())


def is_negated(text: str, start: int, unaccented: Optional[bool] = None) -> bool:
    """Có từ phủ định ngay trước vị trí `start` không: "không hủy", "không muốn hủy", "chưa cần đổi"."""
    if unaccented is None:
        unaccented = is_unaccented(text)
    if unaccented:
        negators, modals = _NEGATORS_UNACCENTED, _NEGATION_MODALS_UNACCENTED
    else:
        negators, modals = _NEGATORS, _NEGATION_MODALS
    before = text[:start].split()[-3:]
    while before and before[-1] in modals:
        before.pop()
    return bool(before) and before[-1] in negators


def remove_spans(text: str, matches: Iterable[re.Match[str]]) -> str:
    """Xoá các đoạn đã khớp (thay bằng khoảng trắng) để bộ khớp sau không đọc lại chúng."""
    chars = list(text)
    for match in matches:
        chars[match.start() : match.end()] = " " * (match.end() - match.start())
    return " ".join("".join(chars).split())
