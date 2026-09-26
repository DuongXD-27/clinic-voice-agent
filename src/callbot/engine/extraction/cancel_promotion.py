"""Nâng AGREE ở câu xác nhận hủy từ tầng ngữ nghĩa, có kiểm chứng — plan
`docs/evidence/t05-cancel-dialogue.md`, đợt 3.

Model chỉ ĐỀ XUẤT mệnh đề hủy (`reply_span`); luật quyết. Được nâng khi:
① luật ra UNCLEAR chỉ vì còn từ ngoài danh sách (`cancel_unclear_cause` là `LEFTOVER`);
③ span tự nó là xác nhận hủy theo đúng luật toàn câu SF-05 (`cancel_clause_confirms`);
④ MỌI từ ngoài span thuộc ngữ pháp lành tính, xét theo vị trí (danh sách cho phép):
   B1 đáp lễ / lời đồng ý / xưng hô / tiểu từ — đúng các tập của luật toàn câu;
   B2 dấu nối kết luận mở câu: "thôi thì", "vậy thì", "thế thì", "ờ thế";
   B3 MỘT mệnh đề lý do có căn cứ, tách khỏi mệnh đề hủy bằng ranh giới do LUẬT xác định:
      R1 [lý do] <dấu ngắt> [span]
      R2 [lý do] nên / cho nên / vậy nên / thế nên [span]   (từ nối liền trước span)
      R3 [span] vì / bởi vì / tại vì / do / tại [lý do]  hoặc  [span] <dấu ngắt> [lý do]

Model có thể chọn span "hủy" trơ — span đó luôn qua ③ — nên chặn chính nằm ở ④. Các tập dưới đây
là của RIÊNG tầng nâng: không dùng lại `agreement._REASON_LINKS`, để đường luật không đổi khi tắt
flag. Thêm một từ / cụm vào đây là nới ngưỡng ghi CANCELLED: mỗi mục mới cần một ca đối lập âm tính.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from callbot.engine.extraction.agreement import (
    UnclearCause,
    cancel_clause_confirms,
    cancel_filler_words,
    cancel_lead_explained,
    cancel_unclear_cause,
)
from callbot.engine.extraction.cancel_reason import DEFAULT as DEFAULT_CANCEL_REASON
from callbot.engine.extraction.cancel_reason import extract_cancel_reason, reason_matches
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    is_unaccented,
    normalize,
    remove_phrases,
    remove_spans,
    strip_diacritics,
)

# Phần ngoài span, sau khi bỏ tiểu từ / xưng hô / đáp lễ, dài hơn thì hỏi lại (chặn bổ sung cho ④)
MAX_REMAINDER_WORDS = 8

_BREAKS = frozenset(",;.!…")
_TOKEN = re.compile(r"[^\W_]+|[,;.!…]")

Words = tuple[str, ...]


def _forms(phrases: Iterable[str], unaccented_exclude: Iterable[str] = ()) -> tuple[Words, Words]:
    """(dạng có dấu, dạng không dấu) của từng cụm, cụm dài xếp trước."""
    accented = {tuple(clean(p).split()) for p in phrases}
    excluded = {tuple(clean(p).split()) for p in unaccented_exclude}
    unaccented = {tuple(strip_diacritics(w) for w in p) for p in accented - excluded}

    def ordered(items: set[Words]) -> tuple[Words, ...]:
        return tuple(sorted(items, key=lambda p: (-len(p), p)))

    return ordered(accented), ordered(unaccented)


# "da" = đã; "u", "o" quá ngắn; "vang a": "a" = ạ hay à
_POLITE = _forms(
    ["vâng", "dạ", "ừ", "ờ", "vâng ạ", "dạ vâng"],
    unaccented_exclude=["dạ", "ừ", "ờ", "vâng ạ", "dạ vâng"],
)
_POLITE_WORDS = frozenset(w for form in _POLITE for p in form for w in p)
# B2. "o the" = ô thế / ở thế
_CONCLUDING = _forms(["thôi thì", "vậy thì", "thế thì", "ờ thế"], unaccented_exclude=["ờ thế"])
# R2: từ nối nhân quả, lý do đứng trước
_CAUSAL = _forms(["nên", "cho nên", "vậy nên", "thế nên"])
# R3: từ nối mở mệnh đề lý do đứng sau. "do" = đó / đỏ; "tai" = tai / tài
_SUBORDINATORS = _forms(["vì", "bởi vì", "tại vì", "do", "tại"], unaccented_exclude=["do", "tại"])
# B3: từ nối được phép TRONG mệnh đề lý do. "qua" = qua; "lam" = làm
_REASON_LINKS = compile_phrases(
    [
        "vì",
        "bởi vì",
        "tại vì",
        "do",
        "tại",
        "bởi",
        "hôm đó",
        "hôm ấy",
        "ngày đó",
        "ngày ấy",
        "dạo này",
        "quá",
        "lắm",
    ],
    unaccented_exclude=["do", "tại", "quá", "lắm"],
)
# Mệnh đề lý do không được chứa động từ hành động: "vì tôi bận việc hủy lịch khác"
_ACTION_VERBS = frozenset(clean(w) for w in ["hủy", "đổi", "đặt", "chuyển"])
_ACTION_VERBS_UNACCENTED = frozenset(strip_diacritics(w) for w in _ACTION_VERBS)


@dataclass(frozen=True)
class _Word:
    text: str
    break_before: bool  # có dấu ngắt , ; . ! … ngay trước từ này


def _words(text: str) -> list[_Word]:
    """Tách từ như `clean`, nhưng giữ dấu ngắt mệnh đề làm cờ trên từ đứng sau nó."""
    words: list[_Word] = []
    pending = False
    for match in _TOKEN.finditer(normalize(text)):
        token = match.group(0)
        if token in _BREAKS:
            pending = True
        else:
            words.append(_Word(token, pending))
            pending = False
    return words


def _text(words: list[_Word]) -> str:
    return " ".join(w.text for w in words)


def _prefix(words: list[_Word], forms: tuple[Words, Words], unaccented: bool) -> int:
    """Số từ của cụm dài nhất trong `forms` khớp ở đầu `words`, liền mạch (không dấu ngắt giữa)."""
    for phrase in forms[1] if unaccented else forms[0]:
        size = len(phrase)
        if (
            len(words) >= size
            and tuple(w.text for w in words[:size]) == phrase
            and not any(w.break_before for w in words[1:size])
        ):
            return size
    return 0


def _suffix(words: list[_Word], forms: tuple[Words, Words], unaccented: bool) -> int:
    for phrase in forms[1] if unaccented else forms[0]:
        size = len(phrase)
        tail = words[-size:] if size <= len(words) else []
        if (
            tail
            and tuple(w.text for w in tail) == phrase
            and not any(w.break_before for w in tail[1:])
        ):
            return size
    return 0


def promotion_rejection(transcript: str, span: Optional[str]) -> Optional[str]:
    """`None` khi được nâng; ngược lại là mã điều kiện không đạt (để log, không log transcript)."""
    if cancel_unclear_cause(transcript) is not UnclearCause.LEFTOVER:
        return "cause"
    words = _words(transcript)
    target = [w.text for w in _words(span or "")]
    if not target:
        return "span"
    size = len(target)
    starts = [
        i for i in range(len(words) - size + 1) if [w.text for w in words[i : i + size]] == target
    ]
    if len(starts) != 1:
        return "span"
    start = starts[0]
    inside = words[start : start + size]
    if any(w.break_before for w in inside[1:]):
        return "span"
    unaccented = is_unaccented(clean(transcript))
    if not cancel_clause_confirms(_text(inside), unaccented):
        return "clause"

    before, after = words[:start], words[start + size :]
    before_ok, before_reason = _before_ok(before, inside[0], unaccented)
    after_ok, after_reason = _after_ok(after, unaccented)
    if not (before_ok and after_ok) or (before_reason and after_reason):
        return "remainder"
    filler = cancel_filler_words(unaccented) | _POLITE_WORDS
    if sum(w.text not in filler for w in before + after) > MAX_REMAINDER_WORDS:
        return "length"
    reason = extract_cancel_reason(transcript)
    if reason.found and reason.value == DEFAULT_CANCEL_REASON:
        # Nhiều lý do khác nhau trong câu: không chọn hộ người gọi
        return "reason_conflict"
    return None


def cancel_promotion_verified(transcript: str, span: Optional[str]) -> bool:
    return promotion_rejection(transcript, span) is None


def _before_ok(before: list[_Word], span_start: _Word, unaccented: bool) -> tuple[bool, bool]:
    """(hợp lệ, có mệnh đề lý do). B2 chỉ ở đầu câu, có thể sau đáp lễ."""
    position = _prefix(before, _CONCLUDING, unaccented)
    if not position:
        polite = _prefix(before, _POLITE, unaccented)
        concluding = _prefix(before[polite:], _CONCLUDING, unaccented) if polite else 0
        position = polite + concluding if concluding else 0
    rest = before[position:]
    if not rest or cancel_lead_explained(_text(rest), unaccented):
        return True, False
    clause = rest[_prefix(rest, _POLITE, unaccented) :]
    causal = _suffix(clause, _CAUSAL, unaccented)
    if causal and _reason_clause(clause[:-causal], unaccented):
        return True, True  # R2
    if span_start.break_before and _reason_clause(clause, unaccented):
        return True, True  # R1
    return False, False


def _after_ok(after: list[_Word], unaccented: bool) -> tuple[bool, bool]:
    """(hợp lệ, có mệnh đề lý do). Tiểu từ / xưng hô liền sau span, rồi tối đa một mệnh đề R3."""
    filler = cancel_filler_words(unaccented)
    position = 0
    while (
        position < len(after)
        and after[position].text in filler
        and not after[position].break_before
    ):
        position += 1
    rest = after[position:]
    if all(w.text in filler for w in rest):
        return True, False
    subordinator = _prefix(rest, _SUBORDINATORS, unaccented)
    if subordinator and _reason_clause(rest[subordinator:], unaccented):
        return True, True  # R3 có từ nối
    if rest[0].break_before and _reason_clause(rest, unaccented):
        return True, True  # R3 có dấu ngắt
    return False, False


def _reason_clause(words: list[_Word], unaccented: bool) -> bool:
    """B3: một mệnh đề liền mạch nêu ĐÚNG MỘT lý do có căn cứ, không bị phủ định, không có động từ
    hành động; mọi từ còn lại là từ nối lý do, đáp lễ, tiểu từ hoặc xưng hô."""
    if not words or any(w.break_before for w in words[1:]):
        return False
    text = _text(words)
    if is_unaccented(text) != unaccented:
        return False
    verbs = _ACTION_VERBS_UNACCENTED if unaccented else _ACTION_VERBS
    if verbs.intersection(text.split()):
        return False
    reason = extract_cancel_reason(text)
    if not reason.found or reason.value == DEFAULT_CANCEL_REASON:
        return False
    rest = remove_spans(text, reason_matches(text, reason.value, unaccented))
    rest = remove_phrases(rest, _REASON_LINKS, unaccented)
    allowed = cancel_filler_words(unaccented) | _POLITE_WORDS
    return all(w in allowed for w in rest.split())
