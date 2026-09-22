"""Adapter cho model ZipFormer CŨ (sherpa-onnx-zipformer-vi-int8-2025-04-20) — dùng để
so sánh công bằng với gipformer1.5 bằng CÙNG bộ công cụ evaluate.py, thay vì trích dẫn
số liệu benchmark cũ chưa tự kiểm chứng lại. Trỏ thẳng path cũ, không đụng .env production
(ZIPFORMER_*_PATH hiện trỏ gipformer1.5)."""

from __future__ import annotations

import time
import wave
from pathlib import Path

from adapters.base import STTResult
from inference.asr.config import ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR
from speech.audio.codec import resample

_ASSETS = Path(__file__).resolve().parents[3] / "src/inference/asr/providers/assets/zipformer"


class ZipformerOldAdapter:
    name = "zipformer-vi-int8-2025-04-20"

    def __init__(self) -> None:
        cfg = ZipFormerConfig(
            encoder_path=str(_ASSETS / "encoder-epoch-12-avg-8.int8.onnx"),
            decoder_path=str(_ASSETS / "decoder-epoch-12-avg-8.onnx"),
            joiner_path=str(_ASSETS / "joiner-epoch-12-avg-8.int8.onnx"),
            tokens_path=str(_ASSETS / "tokens.txt"),
        )
        self._asr = ZipFormerASR(cfg)

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


adapter = ZipformerOldAdapter
