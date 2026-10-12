"""Silero VAD chạy thẳng bằng onnxruntime — cho Silero v5 / v6, theo `FrameClassifier`.

sherpa-onnx nạp được ONNX v5/v6 nhưng cờ lệch bản chính thức (đo 13/10, v6.2.3, 39 655 frame trong
nhiều điều kiện nhiễu: trùng 98,3%; đầu câu muộn hơn p50 30 ms, p90 60 ms). Với pre-roll 300 ms của
ASR web, chừng đó đủ cắt âm đầu câu ở một số câu: qua pipeline đầy đủ WER lượt web 0,178 (sherpa) vs
0,171 (ở đây), hiệu −0,008 [−0,012; −0,003]. Ở đây model chạy như `OnnxWrapper` chính thức của
snakers4/silero-vad (cửa sổ 512 mẫu ở 16 kHz, ghép 64 mẫu cuối của cửa sổ trước, trạng thái
[2, 1, 128]); quyết định "đang nói" theo đúng máy trạng thái `SileroVadModel::IsSpeech` của
sherpa-onnx mà production đang dùng (bắt đầu khi xác suất > ngưỡng liên tục `min_speech_ms`, giữ
khi > ngưỡng − 0,15, nhả sau `min_silence_ms` dưới ngưỡng; chỉ xoá mốc bắt đầu im khi > ngưỡng) —
cùng model v4 thì cờ trùng `SileroVadClassifier` (sherpa) 100% frame (eval/vad-bench/vad_compare.py).

Model v4 bản k2-fsa (đầu vào x, h, c) cũng chạy được — chọn theo tên đầu vào của file ONNX.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

_RATE = 16_000
_WINDOW = 512
_CONTEXT = 64


class SileroOnnxClassifier:
    """Có trạng thái: mỗi luồng audio một instance (như `SileroVadClassifier`)."""

    def __init__(
        self,
        model_path: str,
        *,
        sample_rate: int = 16_000,
        threshold: float = 0.5,
        min_silence_ms: int = 500,
        min_speech_ms: int = 250,
    ) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            model_path, options, providers=["CPUExecutionProvider"]
        )
        names = {i.name for i in self._session.get_inputs()}
        self._v5 = "state" in names
        if self._v5:
            self._state = np.zeros((2, 1, 128), np.float32)
            self._context = np.zeros(_CONTEXT, np.float32)
            self._sr = np.array(_RATE, dtype=np.int64)
        else:
            self._h = np.zeros((2, 1, 64), np.float32)
            self._c = np.zeros((2, 1, 64), np.float32)
        self._threshold = threshold
        self._min_speech = min_speech_ms / 1000
        self._min_silence = min_silence_ms / 1000
        self._resampler: Optional[object] = None
        if sample_rate != _RATE:
            import soxr

            self._resampler = soxr.ResampleStream(
                sample_rate, _RATE, 1, dtype="int16", quality="HQ"
            )
        self._pending = np.empty(0, dtype=np.float32)
        self._now = 0.0
        self._triggered = False
        self._temp_start: Optional[float] = None
        self._temp_end: Optional[float] = None

    def is_speech(self, frame: bytes) -> bool:
        if frame:
            raw = np.frombuffer(frame, dtype=np.int16)
            pcm16 = self._resampler.resample_chunk(raw) if self._resampler is not None else raw
            self._pending = np.concatenate([self._pending, pcm16.astype(np.float32) / 32768.0])
        while len(self._pending) >= _WINDOW:
            window = self._pending[:_WINDOW]
            self._pending = self._pending[_WINDOW:]
            self._now += _WINDOW / _RATE
            self._step(self._prob(window))
        return self._triggered

    def _prob(self, window: np.ndarray) -> float:
        if self._v5:
            x = np.concatenate([self._context, window])[None]
            out, self._state = self._session.run(
                None, {"input": x, "state": self._state, "sr": self._sr}
            )
            self._context = x[0, -_CONTEXT:]
        else:
            out, self._h, self._c = self._session.run(
                None, {"x": window[None], "h": self._h, "c": self._c}
            )
        return float(out[0, 0])

    def _step(self, prob: float) -> None:
        """Máy trạng thái của sherpa-onnx `SileroVadModel::IsSpeech`."""
        threshold = self._threshold
        if prob > threshold and self._temp_end is not None:
            self._temp_end = None
        if not self._triggered:
            if prob > threshold:
                if self._temp_start is None:
                    self._temp_start = self._now
                if self._now - self._temp_start >= self._min_speech:
                    self._triggered = True
            else:
                self._temp_start = None
            return
        if prob > threshold - 0.15:
            return
        if self._temp_end is None:
            self._temp_end = self._now
        if self._now - self._temp_end >= self._min_silence:
            self._triggered = False
            self._temp_start = self._temp_end = None
