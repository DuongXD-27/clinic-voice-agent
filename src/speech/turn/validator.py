"""Turn Validator — lớp quyết định cuối cùng trước khi 1 candidate được chốt thành
UserTurnCompleted, dựa trên bằng chứng âm thanh + độ ổn định transcript thay vì chỉ
duration + is_meaningful_text() như hiện tại (xem TurnController._try_emit()).

Thiết kế theo temp/plan_speech.md: "Turn Validator" dùng 5 tín hiệu (acoustic evidence +
VAD probability + transcript stability + hallucination history + current state/expected
input). Đợt triển khai này CHỈ dùng 3 tín hiệu đầu — `state`/`expected_input` chưa có
nguồn dữ liệu thật (yêu cầu `callbot.engine` trả ExpectedInput, ngoài phạm vi đã thu hẹp
qua xác nhận với người dùng) nhưng interface giữ sẵn 2 tham số này để gắn thêm sau mà
không đổi chữ ký gọi từ TurnController.
"""

import re
from enum import Enum
from typing import Optional

from speech.asr.evidence import StabilityVerdict
from speech.audio.noise_tracker import NoiseEvidence

# Câu 1-2 từ mà ASR không chắc (< `_LOW_CONFIDENCE`) chỉ được giữ khi là câu trả lời thường gặp:
# tiếng động bị nghe thành một từ bất kỳ ("ÔNG" 0,28 khi đập bàn, "ĐÂY" 0,31/0,42 — cuộc gọi thật).
# Không chặn theo độ tin cậy riêng: câu ngắn thật cũng có thể kém chắc ("KHÔNG" 0,335 khi sạch,
# "VÂNG" 0,267; noise-bench 08/10: 20/136 câu ngắn thật < 0,5).
_LOW_CONFIDENCE = 0.5
_ANSWER_WORDS = frozenset(
    {"có", "không", "vâng", "ừ", "ờ", "ừa", "dạ", "ok", "okê", "kê", "đúng", "rồi", "được"}
    | {"chưa", "đồng", "hủy", "đổi", "sai", "phải", "thôi", "alo", "chuẩn", "hả", "gì"}
    | {"dừng", "khoan", "đợi", "chờ"}
)
_ANSWER_PARTICLES = frozenset(
    {"ạ", "à", "nhé", "nha", "em", "anh", "chị", "luôn", "đi", "ừm", "vậy", "thế", "ý", "ô"}
    | {"lại", "đã", "chút", "nào"}
)
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def is_short_answer(text: str, *, max_words: int = 3) -> bool:
    """Câu trả lời/lệnh ngắn thường gặp: "OK EM", "KHÔNG", "ĐÚNG RỒI", "DỪNG LẠI"."""
    words = _NON_WORD_RE.sub(" ", text.lower()).split()
    return (
        0 < len(words) <= max_words
        and all(word in _ANSWER_WORDS or word in _ANSWER_PARTICLES for word in words)
        and any(word in _ANSWER_WORDS for word in words)
    )


class ValidationDecision(str, Enum):
    ACCEPT = "accept"
    WAIT = "wait"
    DROP = "drop"


class TurnValidator:
    """`min_snr_db`: dưới ngưỡng này VÀ text ngắn (<= `max_short_text_words` từ) -> DROP,
    khớp đúng mẫu quan sát thực tế (WebRTC VAD sai trên noise -> ASR ra 1 từ ngắn "ĐÂY"/
    "TẠI", xem docs/reference/livekit-architecture.md §5.4)."""

    def __init__(self, *, min_snr_db: float = 3.0, max_short_text_words: int = 2) -> None:
        self._min_snr_db = min_snr_db
        self._max_short_text_words = max_short_text_words

    def evaluate(
        self,
        candidate_text: str,
        *,
        noise_evidence: Optional[NoiseEvidence] = None,
        vad_probability: Optional[float] = None,
        stability: StabilityVerdict = StabilityVerdict.UNKNOWN,
        state: Optional[str] = None,
        expected_input: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> ValidationDecision:
        if stability == StabilityVerdict.OSCILLATING:
            return ValidationDecision.DROP

        is_short_text = len(candidate_text.split()) <= self._max_short_text_words
        if (
            is_short_text
            and confidence is not None
            and confidence < _LOW_CONFIDENCE
            and not is_short_answer(candidate_text)
        ):
            return ValidationDecision.DROP
        if (
            noise_evidence is not None
            and is_short_text
            and noise_evidence.snr_db < self._min_snr_db
        ):
            return ValidationDecision.DROP

        if stability == StabilityVerdict.CONVERGING:
            return ValidationDecision.ACCEPT

        return ValidationDecision.WAIT
