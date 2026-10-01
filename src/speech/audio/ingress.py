"""Đo audio đầu vào của một cuộc gọi streaming — chỉ số, không giữ audio, không đổi audio.

- Băng thông hiệu dụng: tỉ lệ năng lượng 4,2–7,6 kHz trên các frame có tiếng của vài giây
  đầu. Agent luôn nhận PCM 16 kHz (LiveKit resample), nên codec của SIP không lộ ra ở phía
  agent; G.711 (PCMA/PCMU) để lại gần như không có năng lượng trên 4 kHz, còn mic WebRTC và
  G.722 thì có. Dùng để xác nhận đường SIP đúng narrowband, cùng với SDP phía PJSUA.
- Audio bị rơi: AudioStream của LiveKit có sức chứa giới hạn; khi hàng đợi phía sau đầy, nó
  bỏ frame mà không báo. So thời lượng audio nhận được với thời gian thực trôi qua.
- Mức âm: nền = p10 RMS mọi frame; giọng = trung vị RMS các frame có tiếng (trên ngưỡng), vì
  phần lớn cuộc gọi là im lặng nên phân vị trên mọi frame không phản ánh giọng.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

import numpy as np

_BAND_LOW_HZ = 4_200
_BAND_HIGH_HZ = 7_600
# Frame có RMS trên ngưỡng này mới tính vào băng thông (bỏ khoảng lặng / nhiễu nền).
_ACTIVE_RMS = 300.0
_BAND_ACTIVE_MS = 3_000.0
# Ít hơn chừng này audio có tiếng thì chưa đủ để kết luận băng thông (vd. một tiếng click).
_BAND_MIN_MS = 1_000.0
# Dưới −50 dB năng lượng ở dải cao: coi là narrowband (G.711). Đo 01/10: mic laptop qua xử lý
# của trình duyệt (voiceIsolation) thấp nhất 7e-4; cùng audio qua G.711 8 kHz rồi nâng lên
# 16 kHz còn 4e-9. Cần xác nhận lại bằng cuộc gọi PJSUA thật.
_NARROWBAND_RATIO = 1e-5
_MAX_LEVEL_SAMPLES = 20_000


class IngressMonitor:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.sample_rate: Optional[int] = None
        self.num_channels: Optional[int] = None
        self._first_at: Optional[float] = None
        self._last_at: Optional[float] = None
        self.received_ms = 0.0
        self.frames = 0
        self.max_queue_depth = 0
        self._band_high = 0.0
        self._band_total = 0.0
        self._band_ms = 0.0
        self._levels: list[float] = []
        self._active_levels: list[float] = []

    def observe(
        self, pcm: bytes, sample_rate: int, *, num_channels: int = 1, queue_depth: int = 0
    ) -> None:
        now = self._clock()
        if self._first_at is None:
            self._first_at = now
            self.sample_rate = sample_rate
            self.num_channels = num_channels
        self._last_at = now
        samples = np.frombuffer(pcm, dtype=np.int16)
        if not len(samples):
            return
        self.frames += 1
        self.received_ms += len(samples) / sample_rate * 1000
        self.max_queue_depth = max(self.max_queue_depth, queue_depth)
        x = samples.astype(np.float32)
        rms = float(np.sqrt(np.mean(x * x)))
        if len(self._levels) < _MAX_LEVEL_SAMPLES:
            self._levels.append(rms)
            if rms >= _ACTIVE_RMS:
                self._active_levels.append(rms)
        if rms >= _ACTIVE_RMS and self._band_ms < _BAND_ACTIVE_MS and sample_rate >= 16_000:
            spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
            freqs = np.fft.rfftfreq(len(x), 1 / sample_rate)
            self._band_high += float(
                spectrum[(freqs >= _BAND_LOW_HZ) & (freqs <= _BAND_HIGH_HZ)].sum()
            )
            self._band_total += float(spectrum.sum())
            self._band_ms += len(samples) / sample_rate * 1000

    @property
    def high_band_ratio(self) -> Optional[float]:
        if self._band_total <= 0:
            return None
        return self._band_high / self._band_total

    @property
    def bandwidth(self) -> str:
        ratio = self.high_band_ratio
        if ratio is None or self._band_ms < _BAND_MIN_MS:
            return "unknown"
        return "narrowband" if ratio < _NARROWBAND_RATIO else "wideband"

    def summary(self) -> dict[str, object]:
        wall_ms = (
            (self._last_at - self._first_at) * 1000
            if self._first_at is not None and self._last_at is not None
            else 0.0
        )
        levels = np.array(self._levels) if self._levels else None
        active = np.array(self._active_levels) if self._active_levels else None
        ratio = self.high_band_ratio
        return {
            "sample_rate": self.sample_rate,
            "num_channels": self.num_channels,
            "frames": self.frames,
            "received_ms": round(self.received_ms),
            "wall_ms": round(wall_ms),
            # Thời gian thực trôi qua mà không có audio tương ứng: frame bị rơi (hoặc nguồn
            # ngừng gửi). Một frame nhận cuối cùng chưa được tính vào wall nên trừ ra.
            "missing_ms": round(max(0.0, wall_ms - self.received_ms + self._frame_ms())),
            "max_queue_depth": self.max_queue_depth,
            "high_band_ratio": round(ratio, 6) if ratio is not None else None,
            "bandwidth": self.bandwidth,
            "noise_p10_dbfs": _dbfs(np.percentile(levels, 10)) if levels is not None else None,
            "speech_median_dbfs": _dbfs(np.median(active)) if active is not None else None,
            "active_ratio": round(len(self._active_levels) / len(self._levels), 3)
            if self._levels
            else None,
        }

    def _frame_ms(self) -> float:
        return self.received_ms / self.frames if self.frames else 0.0


def _dbfs(rms: float) -> float:
    return round(20 * math.log10(max(rms, 1.0) / 32768.0), 1)
