"""Xác suất giọng nói thô của Silero, chạy SONG SONG với bộ phân loại sherpa-onnx.

`SileroVadClassifier` (sherpa-onnx `VoiceActivityDetector`) chỉ trả nhị phân, không lộ xác
suất (`last_probability` là 0/1). Probe này chạy cùng file `silero_vad.onnx` (bản v4 của k2-fsa,
nhánh 16 kHz, cửa sổ 512 mẫu, state h/c) trực tiếp bằng onnxruntime. Dùng cho chẩn đoán
(speech/diagnostics.py) và, khi bật `asr_voice_lookback_ms`, để pre-speech của ASR lùi qua phần
giọng sherpa báo trễ. Không thay quyết định speech/không-speech nào của VAD.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_RATE = 16_000
_WINDOW = 512
# Từ đây trở lên là có giọng (ngưỡng mặc định của chính Silero, cũng là ngưỡng sherpa đang dùng).
VOICE_PROBABILITY = 0.5


class SileroProbe:
    def __init__(self, model_path: str, *, sample_rate: int = _RATE) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        # Một luồng: đây là phép đo phụ, không được tranh CPU với ZipFormer/VAD thật.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._pending = np.empty(0, dtype=np.float32)
        self._resampler = None
        if sample_rate != _RATE:
            import soxr

            self._resampler = soxr.ResampleStream(sample_rate, _RATE, 1, dtype="int16")
        self._last: Optional[float] = None

    def probability(self, frame: bytes) -> Optional[float]:
        """Xác suất của cửa sổ 32 ms mới nhất đã đủ mẫu; frame chưa đủ một cửa sổ thì trả lại
        giá trị trước (None nếu chưa có cửa sổ nào)."""
        if not frame:
            return self._last
        raw = np.frombuffer(frame, dtype=np.int16)
        if self._resampler is not None:
            raw = self._resampler.resample_chunk(raw)
        self._pending = np.concatenate([self._pending, raw.astype(np.float32) / 32768.0])
        while len(self._pending) >= _WINDOW:
            window = self._pending[:_WINDOW].reshape(1, _WINDOW)
            self._pending = self._pending[_WINDOW:]
            prob, self._h, self._c = self._session.run(
                None, {"x": window, "h": self._h, "c": self._c}
            )
            self._last = float(prob[0][0])
        return self._last


def build_probe(model_path: Optional[str], sample_rate: int) -> Optional[SileroProbe]:
    """None nếu không có model hoặc thiếu onnxruntime — chẩn đoán vẫn chạy, chỉ không có
    xác suất."""
    if not model_path:
        return None
    try:
        return SileroProbe(model_path, sample_rate=sample_rate)
    except Exception as exc:
        logger.warning("silero_probe: không tạo được, bỏ xác suất (%s)", type(exc).__name__)
        return None
