"""Silero VAD qua sherpa-onnx, theo Protocol `FrameClassifier`.

- Model chỉ chạy ở 16 kHz: frame ở tần số khác được resample bằng `soxr.ResampleStream`
  (giữ trạng thái bộ lọc giữa các frame). Resample từng frame 30 ms rời bằng
  `codec.resample()` làm méo biên frame và Silero không nhận ra giọng nói (0/102 frame).
- `accept_waveform()` phải nhận đúng bội số `window_size` (512 mẫu): sample được đệm lại,
  nếu không model lệch pha và luôn báo im lặng.
- Có trạng thái (kết quả phụ thuộc các frame trước): mỗi luồng audio một instance; muốn
  nhiều nơi dùng chung thì qua `SharedSpeechDetector`.
"""

from typing import Optional

import numpy as np

_SILERO_SAMPLE_RATE = 16_000


class SileroVadClassifier:
    """`model_path`: path tới `silero_vad.onnx` (tải từ k2-fsa/sherpa-onnx releases, xem
    `silero_vad_model_path` trong `config/speech.yaml`). `threshold`: xác suất speech tối thiểu
    (0-1) để `is_speech_detected()` trả True — mặc định 0.5 theo model gốc. `min_silence_ms`:
    hangover của sherpa-onnx (mặc định 0,5 s)."""

    def __init__(
        self,
        model_path: str,
        *,
        sample_rate: int = 8_000,
        threshold: float = 0.5,
        min_silence_ms: int = 500,
    ) -> None:
        import sherpa_onnx

        self._source_rate = sample_rate
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = model_path
        config.silero_vad.threshold = threshold
        # Silero giữ trạng thái "đang nói" thêm chừng này sau khi hết tiếng (hangover) — cộng
        # thẳng vào độ trễ chốt lượt, trước cả vad_end_silence_ms của AsyncStreamingVAD.
        config.silero_vad.min_silence_duration = min_silence_ms / 1000
        config.sample_rate = _SILERO_SAMPLE_RATE
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        self._window_size = config.silero_vad.window_size
        self._resampler: Optional[object] = None
        if sample_rate != _SILERO_SAMPLE_RATE:
            import soxr

            self._resampler = soxr.ResampleStream(
                sample_rate, _SILERO_SAMPLE_RATE, 1, dtype="int16", quality="HQ"
            )
        self._pending = np.empty(0, dtype=np.float32)

    def is_speech(self, frame: bytes) -> bool:
        if not frame:
            return False
        raw = np.frombuffer(frame, dtype=np.int16)
        pcm16 = self._resampler.resample_chunk(raw) if self._resampler is not None else raw
        samples = pcm16.astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, samples])
        while len(self._pending) >= self._window_size:
            window = self._pending[: self._window_size]
            self._pending = self._pending[self._window_size :]
            self._vad.accept_waveform(window)
        # Chỉ đọc cờ is_speech_detected(); đoạn nói mà sherpa-onnx tự cắt và xếp hàng không
        # dùng đến — bỏ đi, nếu không mọi đoạn nói của cả cuộc gọi nằm lại trong bộ nhớ.
        while not self._vad.empty():
            self._vad.pop()
        return self._vad.is_speech_detected()
