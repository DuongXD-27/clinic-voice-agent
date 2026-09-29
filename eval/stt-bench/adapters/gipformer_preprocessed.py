"""Model production (gipformer) chạy qua pipeline tiền xử lý của API /v1/stt (speech.asr.offline).
So với adapters.gipformer (decode nguyên file, không tiền xử lý) để biết tiền xử lý giúp hay hại.

    # /v1/stt/turn: bỏ DC, resample thẳng 16 kHz, khuếch đại clip nhỏ, decode nguyên clip
    python eval/stt-bench/evaluate.py --adapter adapters.gipformer_preprocessed:turn_adapter
    # /v1/stt/transcribe: như trên + cắt đoạn bằng Silero VAD
    python eval/stt-bench/evaluate.py --adapter adapters.gipformer_preprocessed:adapter

Chạy từ thư mục gốc repo (đường dẫn model Silero trong config là tương đối).
"""

from __future__ import annotations

import time
from pathlib import Path

from adapters.base import STTResult
from inference.asr import create_asr_gateway
from speech.asr.offline import transcribe_offline, transcribe_turn
from speech.asr.recognizer import SpeechRecognizer
from speech.asr.vad.silero import SileroVadClassifier
from speech.settings import SpeechSettings


class GipformerPreprocessedAdapter:
    name = "gipformer1.5-68M-rnnt+stt-eval-preprocess"

    def __init__(self) -> None:
        self._recognizer = SpeechRecognizer(create_asr_gateway("zipformer"))
        self._vad_model = SpeechSettings().silero_vad_model_path

    def _vad(self, sample_rate: int) -> SileroVadClassifier:
        return SileroVadClassifier(self._vad_model, sample_rate=sample_rate)

    def transcribe(self, audio_path: Path) -> STTResult:
        start = time.monotonic()
        result = transcribe_offline(
            audio_path.read_bytes(), recognizer=self._recognizer, vad_factory=self._vad
        )
        return STTResult(
            text=result.text,
            latency_ms=(time.monotonic() - start) * 1000,
            metadata={"steps": result.steps, "warnings": result.warnings},
        )


class GipformerTurnAdapter:
    name = "gipformer1.5-68M-rnnt+stt-eval-turn"

    def __init__(self) -> None:
        self._recognizer = SpeechRecognizer(create_asr_gateway("zipformer"))

    def transcribe(self, audio_path: Path) -> STTResult:
        start = time.monotonic()
        result = transcribe_turn(audio_path.read_bytes(), recognizer=self._recognizer)
        return STTResult(
            text=result.text,
            latency_ms=(time.monotonic() - start) * 1000,
            metadata={"steps": result.steps, "warnings": result.warnings},
        )


adapter = GipformerPreprocessedAdapter
turn_adapter = GipformerTurnAdapter
