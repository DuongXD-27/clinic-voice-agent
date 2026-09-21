"""ZipFormer 68M self-host qua sherpa-onnx.

Model `csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20` đã kiểm chứng (xem
temp/plan_mvp_zipformer.md, docs/reference/phone-leg-architecture.md §3.1) là bản
EXPORT OFFLINE (batch) — thiếu metadata streaming (`encoder_dims`) nên chỉ nạp được
qua `OfflineRecognizer`, không phải `OnlineRecognizer`. Vì vậy `transcribe()` nhận
nguyên một đoạn audio đã cắt sẵn (bởi VAD), không có partial transcript tăng dần.
"""

from typing import Any

from inference.asr.base import ASRResult
from inference.asr.config import ZipFormerConfig


class ZipFormerASR:
    input_sample_rate = 16_000

    def __init__(self, config: ZipFormerConfig, *, recognizer: Any = None) -> None:
        self._config = config
        self._recognizer = recognizer

    @property
    def model(self) -> str:
        return self._config.model

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx  # pip install -e ".[speech-zipformer]"

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=self._config.tokens_path,
                encoder=self._config.encoder_path,
                decoder=self._config.decoder_path,
                joiner=self._config.joiner_path,
                num_threads=self._config.num_threads,
                sample_rate=self.input_sample_rate,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
        return self._recognizer

    def transcribe(self, pcm: bytes) -> ASRResult:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        recognizer = self._get_recognizer()
        stream = recognizer.create_stream()
        stream.accept_waveform(self.input_sample_rate, samples)
        recognizer.decode_stream(stream)
        return ASRResult(text=stream.result.text.strip())
