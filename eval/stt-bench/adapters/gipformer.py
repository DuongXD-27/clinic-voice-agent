"""Adapter cho model production hiện tại (đọc qua ZipFormerConfig/ZipFormerASR thật —
dùng chung code path với LiveKit/demo, không tự decode riêng lẻ). Asset thật do
ZIPFORMER_*_PATH trong config/asr.yaml quyết định (mặc định trỏ model gipformer1.5-68M-rnnt,
xem src/inference/asr/providers/assets/zipformer/).
"""

from __future__ import annotations

import time
import wave
from pathlib import Path

from adapters.base import STTResult
from inference.asr.config import ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR
from speech.audio.codec import resample


class GipformerAdapter:
    name = "gipformer1.5-68M-rnnt"

    def __init__(self) -> None:
        self._asr = ZipFormerASR(ZipFormerConfig())

    def transcribe(self, audio_path: Path) -> STTResult:
        with wave.open(str(audio_path), "rb") as w:
            rate = w.getframerate()
            pcm = w.readframes(w.getnframes())
        if rate != self._asr.input_sample_rate:
            pcm = resample(pcm, rate, self._asr.input_sample_rate)
        start = time.monotonic()
        result = self._asr.transcribe(pcm)
        latency_ms = (time.monotonic() - start) * 1000
        return STTResult(text=result.text, latency_ms=latency_ms)


adapter = GipformerAdapter
