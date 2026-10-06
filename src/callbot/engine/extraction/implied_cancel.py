"""Lý do hủy đủ để hiểu là yêu cầu hủy — QC `qc-cn-03-went-elsewhere`.

"Tôi khám ở bệnh viện khác rồi" ở câu đọc lịch / "đổi hay hủy" không còn gì để đổi: Dialogue vào thẳng
câu xác nhận hủy thay vì hỏi "đổi hay hủy" thêm một lượt. Đây CHỈ là lượt yêu cầu (REQUEST): lệnh ghi vẫn
cần lượt xác nhận sau có động từ "hủy" tường minh (§1.1.4, SF-05).

Hàm thuần trên transcript; extractor tự xét câu hỏi đang chờ, hướng gọi, intent luật và lâm sàng.
Nâng khi cụm lý do:
- thuộc WENT_ELSEWHERE kèm dấu hiệu đã xảy ra ("... rồi", "đã ..."): "tôi định khám chỗ khác",
  "giờ đó tôi có lịch khám ở bệnh viện khác" (trùng giờ, có thể muốn dời) thì không;
- hoặc là cụm NO_LONGER_NEEDED dứt khoát ("khỏi rồi", "hết đau rồi"); "đỡ rồi" chưa phải không cần khám;
- không có từ phủ định trước nó trong cùng mệnh đề ("tôi không khám ở bệnh viện khác đâu");
- trong câu không phải câu hỏi, không có "nhưng", không ngập ngừng.
Thiếu một điều kiện thì không nâng: lượt đi đường cũ (hỏi "đổi hay hủy"), không mất gì.
"""

import re
from typing import Optional

from callbot.engine.extraction.agreement import asks_or_hesitates
from callbot.engine.extraction.cancel_reason import extract_cancel_reason, reason_matches
from callbot.engine.extraction.schema import Field
from callbot.engine.extraction.text import (
    clean,
    is_unaccented,
    negators,
    normalize,
    strip_diacritics,
)
from callbot.engine.types import CancelReason

_CLAUSE_BREAK = re.compile(r"[,;.!?…]")
# "da" không dấu có thể là "dạ": chỉ nhận "roi"
_DONE_AFTER = frozenset({"rồi", "roi"})
_DONE_BEFORE = frozenset({"đã"})
_NO_LONGER_NEEDED_DEFINITE = frozenset(
    clean(p) for p in ["khỏi rồi", "hết đau rồi", "khỏe rồi", "không cần khám nữa", "không cần nữa"]
)
_NO_LONGER_NEEDED_DEFINITE_UNACCENTED = frozenset(
    strip_diacritics(p) for p in _NO_LONGER_NEEDED_DEFINITE
)


def implied_cancel(transcript: str, reason: Field[CancelReason]) -> Optional[str]:
    """Span lý do khi lượt này là yêu cầu hủy; `None` khi không. `reason` là kết quả
    `extract_cancel_reason` trên cả câu — nhiều lý do (UNSPECIFIED) thì không nâng."""
    if not reason.found or reason.value not in ("WENT_ELSEWHERE", "NO_LONGER_NEEDED"):
        return None
    if asks_or_hesitates(transcript):
        return None
    for clause in _CLAUSE_BREAK.split(normalize(transcript)):
        text = clean(clause)
        if extract_cancel_reason(text).value == reason.value:
            return reason.span if _definite(text, reason.value) else None
    return None


def _definite(clause: str, reason: CancelReason) -> bool:
    unaccented = is_unaccented(clause)
    matches = reason_matches(clause, reason, unaccented)
    if not matches:
        return False
    start = min(m.start() for m in matches)
    before, rest = clause[:start].split(), clause[start:].split()
    if negators(unaccented).intersection(before):
        return False
    if reason == "WENT_ELSEWHERE":
        return bool(_DONE_AFTER.intersection(rest)) or (
            not unaccented and bool(_DONE_BEFORE.intersection(before))
        )
    definite = _NO_LONGER_NEEDED_DEFINITE_UNACCENTED if unaccented else _NO_LONGER_NEEDED_DEFINITE
    return any(m.group(0) in definite for m in matches)
