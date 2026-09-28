"""Theo dõi noise floor liên tục — cung cấp bằng chứng SNR cho Speech Admission/Turn
Validator, độc lập với quyết định speech/non-speech của VAD (VAD có thể sai trên noise
phòng không đồng đều, xem docs/reference/livekit-architecture.md §5.4).
"""

from dataclasses import dataclass

import numpy as np

_EPS = 1e-6


@dataclass(frozen=True)
class NoiseEvidence:
    rms: float
    noise_floor: float
    snr_db: float


class NoiseTracker:
    """`floor_alpha`: hệ số EMA cập nhật `noise_floor` — chỉ cập nhật trên frame
    `is_speech=False` để speech thật không tự kéo nền nhiễu ước tính lên cao."""

    def __init__(self, *, floor_alpha: float = 0.05, initial_floor: float = 50.0) -> None:
        self._floor_alpha = floor_alpha
        self._noise_floor = initial_floor

    def observe(self, frame: bytes, is_speech: bool) -> NoiseEvidence:
        """Đo + cập nhật floor trong 1 bước — dùng khi caller không cần tách quyết định
        cập nhật floor khỏi lúc đo (vd. TurnValidator's tracker: is_speech đã CHẮC CHẮN,
        không có bước "REJECT nhưng có thể vẫn là speech thật" ở giữa). `noise_floor` trong
        kết quả trả về là giá trị SAU khi cập nhật (khớp hành vi gốc trước khi tách peek/
        commit_floor) — khác `peek()` luôn trả floor TRƯỚC khi biết caller sẽ quyết định gì."""
        evidence = self.peek(frame)
        if not is_speech:
            self.commit_floor(evidence)
            return self.peek(frame)
        return evidence

    def peek(self, frame: bytes) -> NoiseEvidence:
        """Đo SNR dựa trên `noise_floor` HIỆN TẠI, KHÔNG cập nhật floor — dùng khi caller
        cần biết SNR trước khi tự quyết định is_speech "thật" hay không (Speech Admission:
        low_snr/too_short vẫn có thể là speech thật, không nên kéo floor lên vì đoán sai;
        chỉ no_speech mới chắc chắn là nền nhiễu, gọi `commit_floor()` riêng sau đó)."""
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        snr_db = 20.0 * np.log10(max(rms, _EPS) / max(self._noise_floor, _EPS))
        return NoiseEvidence(rms=rms, noise_floor=self._noise_floor, snr_db=float(snr_db))

    def commit_floor(self, evidence: NoiseEvidence) -> None:
        """Cập nhật floor bằng `rms` của 1 `NoiseEvidence` đã đo qua `peek()` — gọi CHỈ khi
        caller đã tự xác nhận chắc chắn đây là nền nhiễu (không phải speech), sau khi có
        đủ bằng chứng để quyết định (vd. AdmissionDecision.reason == "no_speech")."""
        self._update_floor(evidence.rms)

    def _update_floor(self, rms: float) -> None:
        self._noise_floor = self._floor_alpha * rms + (1 - self._floor_alpha) * self._noise_floor
