"""cancel_reason — thiết kế v1.1 §5.8.

Đây là trường GHI VÀO HỒ SƠ: chỉ ánh xạ cụm từ tường minh, không suy diễn lý do từ ngữ cảnh.
Nêu nhiều lý do khác nhau trong cùng câu -> UNSPECIFIED (không chọn hộ người gọi).

`provenance` phân biệt hai cách ra UNSPECIFIED, vì Dialogue xử lý khác nhau (T-05 §3.2):
- `NONE`  — lượt này không có nội dung lý do nào: giữ nguyên lý do đã ghi nhận trước đó.
- khác NONE, `value == "UNSPECIFIED"` — người gọi CÓ nói lý do nhưng nêu nhiều lý do không chọn
  được; `span` là các cụm đã khớp. Lý do cũ bị thay bằng UNSPECIFIED, không giữ ngầm.
"""

from callbot.engine.extraction.schema import Field, Provenance
from callbot.engine.extraction.text import (
    PhraseSet,
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
)
from callbot.engine.types import CancelReason

DEFAULT: CancelReason = "UNSPECIFIED"

_PHRASES: dict[CancelReason, PhraseSet] = {
    "PATIENT_UNAVAILABLE": compile_phrases(
        [
            "bận",
            "đi công tác",
            "không đi được",
            "không đến được",
            "có việc",
            "vướng việc",
            "không sắp xếp được",
            "kẹt việc",
            "về quê",
        ],
        unaccented_exclude=["bận"],  # "ban" = bạn
    ),
    "NO_LONGER_NEEDED": compile_phrases(
        [
            "khỏi rồi",
            "đỡ rồi",
            "hết đau rồi",
            "không cần khám nữa",
            "không cần nữa",
            "không cần khám",
            "khỏe rồi",
        ],
        unaccented_exclude=["đỡ rồi"],  # "do roi" = đó rồi
    ),
    "WENT_ELSEWHERE": compile_phrases(
        [
            "khám chỗ khác",
            "đi viện khác",
            "khám ở nơi khác",
            "bệnh viện khác",
            "phòng khám khác",
            "chỗ khác rồi",
            "nơi khác rồi",
            "khám ở chỗ khác",
        ]
    ),
    "COST": compile_phrases(
        ["đắt", "đắt quá", "không đủ tiền", "tốn kém", "chi phí cao", "hết tiền", "không có tiền"],
        unaccented_exclude=["đắt", "đắt quá"],  # "dat" = đặt / đạt / đất
    ),
}


def extract_cancel_reason(transcript: str) -> Field[CancelReason]:
    text = clean(transcript)
    unaccented = is_unaccented(text)
    hits: dict[CancelReason, str] = {}
    for reason, phrases in _PHRASES.items():
        # "không bận" không phải lý do bận
        match = find_phrase(text, phrases, allow_negated=False, unaccented=unaccented)
        if match is not None:
            hits[reason] = match.group(0)

    if not hits:
        return Field.nothing(DEFAULT)
    provenance = Provenance.NORMALIZED if unaccented else Provenance.EXACT
    if len(hits) > 1:
        # Có tín hiệu lý do nhưng mâu thuẫn: báo là đã thấy (provenance != NONE) với giá trị mặc định,
        # để Dialogue biết phải bỏ lý do cũ chứ không phải bỏ qua lượt này.
        # `hits` theo thứ tự `_PHRASES`, nên span không đổi theo thứ tự người gọi nói
        return Field(DEFAULT, provenance, span=" + ".join(hits.values()))
    reason, span = next(iter(hits.items()))
    return Field(reason, provenance, span=span)
