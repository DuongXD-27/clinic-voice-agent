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
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        if not is_speech:
            self._noise_floor = (
                self._floor_alpha * rms + (1 - self._floor_alpha) * self._noise_floor
            )
        snr_db = 20.0 * np.log10(max(rms, _EPS) / max(self._noise_floor, _EPS))
        return NoiseEvidence(rms=rms, noise_floor=self._noise_floor, snr_db=float(snr_db))
