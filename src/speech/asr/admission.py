"""Speech Admission — quyết định có đẩy 1 frame vào ASR hay không, dựa trên VAD + duration
+ bằng chứng SNR (NoiseTracker), TRƯỚC khi frame vào `asr_queue` trong `pipeline.py::_fanout()`.

Đây là lớp lọc ĐẦU TIÊN, độc lập với lớp gating nội bộ mà từng ASR provider đã tự làm
(`ZipFormerASR.stream()`/`ElevenLabsRealtimeASR.stream()` đều tự gọi
`silence_classifier.is_speech(frame)` riêng) — không thay thế 2 lớp đó, chỉ giảm tải bằng
cách chặn sớm hơn, dựa trên tín hiệu mạnh hơn (SNR liên tục, không chỉ 1 frame is_speech
đơn lẻ). `vad_queue` KHÔNG bị lọc bởi Admission — VAD cần thấy MỌI frame để tự quyết định
speech_start/speech_end đúng.
"""

from dataclasses import dataclass

from speech.audio.noise_tracker import NoiseEvidence


@dataclass(frozen=True)
class AdmissionDecision:
    admit: bool
    reason: str  # "ok" | "low_snr" | "too_short" | "no_speech"


class SpeechAdmission:
    """`min_snr_db`: SNR tối thiểu (so với noise floor ước tính) để 1 frame speech mới
    (chưa có admission YES liền trước) được đẩy vào ASR. `min_speech_ms`: audio speech
    liên tục tối thiểu trước khi admit — cùng tinh thần `TurnController.min_speech_ms`
    nhưng áp dụng SỚM hơn (chặn từ nguồn, không chỉ discard candidate sau khi đã tốn
    compute ASR). Frame NỐI TIẾP của 1 đoạn đã admit (`already_admitted=True`) luôn được
    admit tiếp dù SNR dao động xuống thấp tạm thời — tránh cắt giữa câu khi người nói hạ
    giọng."""

    def __init__(self, *, min_snr_db: float = 6.0, min_speech_ms: int = 150) -> None:
        self._min_snr_db = min_snr_db
        self._min_speech_ms = min_speech_ms

    def evaluate(
        self,
        *,
        is_speech: bool,
        evidence: NoiseEvidence,
        speech_ms_so_far: float,
        already_admitted: bool,
    ) -> AdmissionDecision:
        if not is_speech and not already_admitted:
            return AdmissionDecision(admit=False, reason="no_speech")
        if already_admitted:
            return AdmissionDecision(admit=True, reason="ok")
        if evidence.snr_db < self._min_snr_db:
            return AdmissionDecision(admit=False, reason="low_snr")
        if speech_ms_so_far < self._min_speech_ms:
            return AdmissionDecision(admit=False, reason="too_short")
        return AdmissionDecision(admit=True, reason="ok")
