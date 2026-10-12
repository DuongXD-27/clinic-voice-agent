"""Lý do hủy đủ để hiểu là yêu cầu hủy — QC `qc-cn-03-went-elsewhere`.

"Tôi khám ở bệnh viện khác rồi" ở câu đọc lịch / "đổi hay hủy" không còn gì để đổi: Dialogue vào thẳng
câu xác nhận hủy thay vì hỏi "đổi hay hủy" thêm một lượt. Đây CHỈ là lượt yêu cầu (REQUEST): lệnh ghi vẫn
cần lượt xác nhận sau có động từ "hủy" tường minh (§1.1.4, SF-05).

Luật này là đường tắt cho câu NGẮN, RÕ, không cố hiểu câu dài. Nó chỉ nhận một khuôn: (lời đáp ngắn
"không" / "dạ" ...,) + chủ ngữ + cụm lý do + "rồi" / tiểu từ. Ví dụ "Không, tôi khám chỗ khác rồi",
"tôi đã khám ở nơi khác", "Tôi khỏi rồi em". Câu có thêm bất cứ từ nào ngoài khuôn — dự định ("tôi
định / sẽ khám chỗ khác"), đặt lịch nơi khác ("tôi đã đặt hẹn ở bệnh viện khác"), "rồi" nghĩa là "sau
đó" ("... rồi báo lại"), phủ định, câu hỏi, "nhưng", không chắc — đều không nâng: luật intent ra NONE
và lượt đi tuyến ngữ nghĩa (INTENT_UNCLEAR). Không có model thì đi đường cũ như trước khi có luật này
(thường là "em chưa hiểu"; hỏi "đổi hay hủy" khi câu có lời từ chối). Cụm lý do luật không biết ("khám
ở viện khác rồi") cũng để model đọc, không thêm vào danh sách.
Không liệt kê các cách nói "không phải đã khám": khuôn nhận vào mới là thứ được liệt kê.

- WENT_ELSEWHERE cần dấu hiệu đã xảy ra: "rồi" từ cụm lý do trở đi, hoặc "đã" trước nó (câu có dấu).
- NO_LONGER_NEEDED chỉ nhận cụm dứt khoát ("khỏi rồi", "không cần nữa"); "đỡ rồi" chưa phải không cần
  khám.
- Nhiều lý do (UNSPECIFIED) thì không nâng.
"""

import re
from typing import Optional

from callbot.engine.extraction.agreement import undecided_request
from callbot.engine.extraction.cancel_reason import extract_cancel_reason, reason_matches
from callbot.engine.extraction.schema import Field
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
    normalize,
    strip_diacritics,
)
from callbot.engine.types import CancelReason

_CLAUSE_BREAK = re.compile(r"[,;.!?…]")
# Mệnh đề đáp ngắn đứng riêng trước câu lý do: "Không, tôi khám chỗ khác rồi"
_ANSWER_WORDS = ["không", "chưa", "dạ", "vâng", "ừ", "à", "ờ", "ạ", "em", "ơi", "thôi"]
# Được đứng trước cụm lý do: chủ ngữ, tiếng đệm, "đã", động từ đi khám
_LEAD_WORDS = [
    "tôi", "em", "mình", "con", "cháu", "nhà", "vợ", "chồng", "bố", "mẹ", "ba", "má",
    "anh", "chị", "cô", "chú", "bác", "ông", "bà", "dạ", "vâng", "à", "ờ", "thì", "cũng", "đã",
    "khám", "đi", "đến", "tới", "sang", "qua", "ở",
]  # fmt: skip
# Được đứng sau cụm lý do
_TAIL_WORDS = [
    "rồi", "ạ", "à", "nhé", "nha", "mà", "đấy", "đó", "luôn", "cả", "hết", "em", "anh", "chị",
    "cô", "chú", "bác", "ơi",
]  # fmt: skip


def _words(words: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    accented = frozenset(clean(w) for w in words)
    return accented, frozenset(strip_diacritics(w) for w in accented)


_ANSWER = _words(_ANSWER_WORDS)
_LEAD = _words(_LEAD_WORDS)
_TAIL = _words(_TAIL_WORDS)
# "da" không dấu có thể là "dạ": câu không dấu chỉ nhận "roi"
_DONE_AFTER = frozenset({"rồi", "roi"})
_DONE_BEFORE = clean("đã")
_NO_LONGER_NEEDED_DEFINITE = _words(
    ["khỏi rồi", "hết đau rồi", "khỏe rồi", "không cần khám nữa", "không cần nữa"]
)


def implied_cancel(transcript: str, reason: Field[CancelReason]) -> Optional[str]:
    """Span lý do khi lượt này là yêu cầu hủy; `None` khi không. `reason` là kết quả
    `extract_cancel_reason` trên cả câu."""
    if not reason.found or reason.value not in ("WENT_ELSEWHERE", "NO_LONGER_NEEDED"):
        return None
    if "?" in transcript:
        return None
    clauses = [c for c in (clean(part) for part in _CLAUSE_BREAK.split(normalize(transcript))) if c]
    reason_clauses = [c for c in clauses if extract_cancel_reason(c).value == reason.value]
    if len(reason_clauses) != 1:
        return None
    for clause in clauses:
        if clause is not reason_clauses[0] and not _only(clause.split(), _ANSWER, clause):
            return None
    return reason.span if _fits(reason_clauses[0], reason.value) else None


def _fits(clause: str, reason: CancelReason) -> bool:
    unaccented = is_unaccented(clause)
    matches = reason_matches(clause, reason, unaccented)
    if not matches:
        return False
    start, end = min(m.start() for m in matches), max(m.end() for m in matches)
    if _gap(matches):
        # Hai cụm lý do cách nhau bởi từ khác: "Tôi khỏi rồi nhưng không chắc là khỏe rồi"
        return False
    before, after = clause[:start].split(), clause[end:].split()
    if not (_only(before, _LEAD, clause) and _only(after, _TAIL, clause)):
        return False
    if reason == "NO_LONGER_NEEDED":
        definite = _NO_LONGER_NEEDED_DEFINITE[1 if unaccented else 0]
        return any(m.group(0) in definite for m in matches)
    done_after = bool(_DONE_AFTER.intersection(clause[start:].split()))
    return done_after or (not unaccented and _DONE_BEFORE in before)


def _gap(matches: list[re.Match[str]]) -> bool:
    """Các lần khớp không phủ liền một đoạn: còn chữ nằm giữa hai cụm."""
    ordered = sorted(matches, key=lambda m: m.start())
    reach = ordered[0].end()
    for match in ordered[1:]:
        if match.string[reach : match.start()].strip():
            return True
        reach = max(reach, match.end())
    return False


def _only(words: list[str], allowed: tuple[frozenset[str], frozenset[str]], clause: str) -> bool:
    return set(words) <= allowed[1 if is_unaccented(clause) else 0]


# --- Lý do do MODEL đọc ra -------------------------------------------------------------------

# Việc chưa xảy ra / nói về đúng hôm hẹn: "tuần sau tôi khám chỗ khác rồi", "tôi định khám chỗ khác",
# "tôi đã đặt hẹn ở bệnh viện khác", "tối đó tôi đến viện khác rồi" — còn lịch để đổi, hỏi "đổi hay hủy".
_PLANNED = compile_phrases(
    [
        "sẽ", "định", "dự định", "sắp", "mai", "ngày mai", "hôm sau", "tuần sau", "tháng sau",
        "tới đây", "sắp tới", "đặt hẹn", "đặt lịch", "có hẹn", "có lịch", "hôm đó", "ngày đó",
        "tối đó", "sáng đó", "chiều đó", "giờ đó", "lúc đó", "hôm ấy", "bữa đó",
    ]
)  # fmt: skip
# Người gọi tự thấy chưa chắc: "tôi hết đau rồi, chắc không cần nữa đâu" (không gồm "chắc chắn")
_SOFTENED = re.compile(r"(?<!\w)(?:chắc(?! chắn)|có lẽ|hình như|có khi|không chắc)(?!\w)")
_DONE = re.compile(r"(?<!\w)(?:rồi|đã|xong)(?!\w)")


def implied_cancel_from_model(transcript: str, reason: Optional[str], span: Optional[str]) -> bool:
    """Lý do model đọc ra ở câu đọc lịch / "đổi hay hủy" đủ để hiểu là yêu cầu hủy — cùng nghĩa
    với `implied_cancel` của luật nhưng cho cụm luật không biết ("khám ở viện tỉnh rồi", "khỏi bệnh
    rồi"). Vẫn CHỈ là lượt yêu cầu: lệnh ghi cần lượt xác nhận có động từ hủy (§1.1.4, SF-05).

    Điều kiện: mã WENT_ELSEWHERE / NO_LONGER_NEEDED, span có dấu hiệu đã xảy ra ("rồi" / "đã"), câu
    có dấu, không phải câu hỏi, không ngập ngừng / điều kiện / kể lại, không nói về việc sắp tới.
    """
    if reason not in ("WENT_ELSEWHERE", "NO_LONGER_NEEDED") or not span or "?" in transcript:
        return False
    text, part = clean(transcript), clean(span)
    if not part or part not in text or is_unaccented(text):
        # Không dấu: "da" là đã / dạ, "roi" mơ hồ -> để luật và câu hỏi lại xử lý
        return False
    if undecided_request(transcript, part) or _SOFTENED.search(text):
        return False
    if find_phrase(text, _PLANNED) is not None:
        return False
    return _DONE.search(part) is not None
