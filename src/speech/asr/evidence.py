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
    lần 1 text NGẮN (<= `_MAX_OSCILLATION_WORDS` từ) phải xuất hiện trở lại trong window,
    mỗi lần cách nhau bởi text khác (mẫu "đây"→"tại"→"có"→"đây"), để coi là OSCILLATING."""

    def __init__(self, *, window: int = 5, oscillation_repeat_threshold: int = 2) -> None:
        self._window: "deque[str]" = deque(maxlen=window)
        self._repeat_threshold = oscillation_repeat_threshold

    def observe(self, event) -> StabilityVerdict:
        text = event.text.strip().lower()
        if not text:
            return StabilityVerdict.UNKNOWN
        previous = self._window[-1] if self._window else None
        self._window.append(text)
        # Mẫu ảo giác chỉ nói về chính chữ ngắn đang xét. Câu dài tới sau các partial ngắn lật qua
        # lại là ASR đã nghe ra thêm (GipFormer decode lại phần đầu câu: "HAI TỶ" -> "HAI THẾ" ->
        # "HAI TỶ" -> "CÓ AI THẤY KHÔNG", 09/10): cửa sổ còn giữ các partial đó thì Validator
        # DROP lượt thật — kể cả sau khi ngắt lời đã được xác nhận (review PR #110).
        if len(text.split()) <= _MAX_OSCILLATION_WORDS and self._is_oscillating():
            return StabilityVerdict.OSCILLATING
        if previous is not None and self._is_converging(previous, text):
            return StabilityVerdict.CONVERGING
        return StabilityVerdict.UNKNOWN

    def _is_oscillating(self) -> bool:
        """Dao động = một text ngắn QUAY LẠI sau khi đã đổi sang text khác (A→B→A, vd.
        "đây"→"tại"→"có"→"đây"). Lặp liền nhau không tính ("có"→"có"→"có" là người dùng
        thật sự nói "có"); đổi một lần rồi giữ nguyên là hội tụ. Bug đo 28/09 (bộ câu ngắn
        của eval/noise-bench): "ĐƯỢC"→"VÂNG"→"VÂNG", SNR 58 dB, bị DROP vì luật cũ chỉ đếm
        "một text xuất hiện >= 2 lần và có >= 2 text khác nhau"."""
        runs: list[str] = []
        for text in self._window:
            if len(text.split()) > _MAX_OSCILLATION_WORDS:
                continue
            if not runs or runs[-1] != text:
                runs.append(text)
        return any(runs.count(text) >= self._repeat_threshold for text in set(runs))

    def _is_converging(self, previous: str, current: str) -> bool:
        from rapidfuzz import fuzz

        if len(current) < len(previous):
            return False
        similarity = fuzz.ratio(previous, current)
        return similarity >= _SIMILARITY_THRESHOLD

    def reset(self) -> None:
        self._window.clear()
