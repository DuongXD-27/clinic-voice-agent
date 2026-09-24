"""Transcript Evidence — theo dõi chuỗi partial transcript liên tiếp để phân biệt hội tụ
dần (câu đang hình thành đúng, "t"→"tôi"→"tôi muốn") với dao động lặp (dấu hiệu
hallucination, "đây"→"tại"→"có"→"đây" — xem docs/reference/livekit-architecture.md §5.4).

`TranscriptEvent` (`speech.types`) là bản chụp tức thời per-event (frozen, không giữ lịch
sử) — 2 consumer hiện tại (`TurnController.on_transcript_event`,
`InterruptionController.on_partial_transcript`) chỉ đọc rồi gán đè/so tức thời. Đánh giá
"dao động lặp" CẦN nhìn nhiều event liên tiếp, nên sống ở tracker riêng này, không phải
thêm field vào TranscriptEvent — tiêu thụ song song tại `_drain_asr()`
(`speech/asr/pipeline.py`), giống cách `interruption.on_partial_transcript()` đã được
"tiêm" song song với `controller.on_transcript_event()` mà không sửa TurnController.
"""

from collections import deque
from enum import Enum


class StabilityVerdict(str, Enum):
    CONVERGING = "converging"
    OSCILLATING = "oscillating"
    UNKNOWN = "unknown"


_MAX_OSCILLATION_WORDS = 2
_SIMILARITY_THRESHOLD = 60.0


class TranscriptEvidenceTracker:
    """`window`: số text gần nhất giữ lại để đánh giá. `oscillation_repeat_threshold`: số
    lần 1 text NGẮN (<= `_MAX_OSCILLATION_WORDS` từ) phải xuất hiện lặp lại trong window
    (không tính liên tiếp — xen kẽ vẫn tính, đúng mẫu "đây"→"tại"→"có"→"đây") để coi là
    OSCILLATING."""

    def __init__(self, *, window: int = 5, oscillation_repeat_threshold: int = 2) -> None:
        self._window: "deque[str]" = deque(maxlen=window)
        self._repeat_threshold = oscillation_repeat_threshold
        self._last_verdict = StabilityVerdict.UNKNOWN

    @property
    def last_verdict(self) -> StabilityVerdict:
        return self._last_verdict

    def observe(self, event) -> StabilityVerdict:
        text = event.text.strip().lower()
        if not text:
            self._last_verdict = StabilityVerdict.UNKNOWN
            return self._last_verdict

        previous = self._window[-1] if self._window else None
        self._window.append(text)

        if self._is_oscillating():
            self._last_verdict = StabilityVerdict.OSCILLATING
        elif (
            previous is not None and len(self._window) >= 2 and self._is_converging(previous, text)
        ):
            self._last_verdict = StabilityVerdict.CONVERGING
        else:
            self._last_verdict = StabilityVerdict.UNKNOWN
        return self._last_verdict

    def _is_oscillating(self) -> bool:
        short_texts = [t for t in self._window if len(t.split()) <= _MAX_OSCILLATION_WORDS]
        if not short_texts:
            return False
        counts: dict[str, int] = {}
        for t in short_texts:
            counts[t] = counts.get(t, 0) + 1
        most_common = max(counts.values())
        # "Dao động" nghĩa là KHÔNG đơn điệu tăng dần độ dài — nếu toàn bộ window chỉ có
        # 1 giá trị duy nhất lặp lại (không đổi qua lại giữa nhiều giá trị), đó là hội tụ
        # ổn định (ví dụ "có" lặp lại vì user thật sự chỉ nói "có"), không phải hallucination.
        distinct_short = len(counts)
        return most_common >= self._repeat_threshold and distinct_short >= 2

    def _is_converging(self, previous: str, current: str) -> bool:
        from rapidfuzz import fuzz

        if len(current) < len(previous):
            return False
        similarity = fuzz.ratio(previous, current)
        return similarity >= _SIMILARITY_THRESHOLD

    def reset(self) -> None:
        self._window.clear()
