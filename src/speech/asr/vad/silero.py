"""Silero VAD qua sherpa-onnx — dùng để benchmark so với `WebRtcVadClassifier` trên audio
noise thật (xem docs/reference/livekit-architecture.md §5.4). Model Silero CHỈ hỗ trợ
16000Hz nội bộ (khác WebRTC VAD hỗ trợ trực tiếp 8/16/32/48kHz) — đã xác nhận thực nghiệm
(`sherpa_onnx.VoiceActivityDetector` raise lỗi cứng khi cấu hình sample_rate=8000).
`SileroVadClassifier` resample MỌI frame nhận được về 16kHz trước khi feed vào model, để
vẫn cắm được vào `FrameClassifier` Protocol (`is_speech(frame) -> bool`) mà không đổi
`StreamingVAD`/`AsyncStreamingVAD` (chúng gọi frame ở sample_rate/frame_ms của pipeline).

Khác WebRTC VAD (phân loại tức thời 1 frame độc lập), `VoiceActivityDetector` của
sherpa-onnx là STATEFUL: giữ buffer nội bộ, `is_speech_detected()` đọc trạng thái tích luỹ
sau `accept_waveform()`, không phải quyết định riêng cho từng frame. `is_speech()` ở đây vẫn
tuân thủ đúng chữ ký Protocol (nhận 1 frame, trả 1 bool), nhưng giá trị trả về phụ thuộc
lịch sử các lần gọi trước — không an toàn dùng nhiều instance chia sẻ cùng 1 `sherpa_onnx.
VoiceActivityDetector`, mỗi call cần 1 `SileroVadClassifier` riêng (giống quy ước hiện có
của `WebRtcVadClassifier`, xem StreamingVAD/AsyncStreamingVAD docstring "không được cho hai
consumer đồng thời dùng chung một instance").

2 bug thật đã gặp lúc viết, cả hai đều khiến `is_speech_detected()` trả `False` cố định dù
audio là giọng nói người thật rõ ràng (xác nhận qua thực nghiệm trên file có câu "Nguyễn Văn
A" — cả 2 lỗi độc lập đều tái hiện y hệt 0/102 frame):

1. `accept_waveform()` chỉ cập nhật đúng trạng thái nội bộ khi được feed CHÍNH XÁC bội số
   `window_size` (512 samples, đọc từ `SileroVadModelConfig`) mỗi lần gọi — feed 480
   samples/lần (khớp 30ms @16kHz, tưởng hợp lý vì đúng `FRAME_MS` của pipeline) khiến model
   "lệch pha" với window nội bộ. Sửa: tự đệm sample vào 1 buffer nội bộ, chỉ gọi
   `accept_waveform()` theo đúng bội số `window_size`.
2. Dùng `speech.audio.codec.resample()` (soxr, stateless) để resample TỪNG FRAME 30ms riêng
   lẻ — dù đã sửa lỗi 1, kết quả vẫn 0/102. Nguyên nhân: `soxr.resample()` là bộ lọc FIR có
   edge effect phụ thuộc ngữ cảnh; gọi độc lập trên từng đoạn 480-sample ngắn tạo méo phổ tần
   ở biên mỗi frame đủ lớn để Silero (nhạy với đặc trưng phổ tinh vi hơn WebRTC nhiều) không
   còn nhận ra giọng nói — resample cả file 1 lần cho kết quả đúng (42/96), resample từng
   frame cho 0/102 trên CÙNG audio. Sửa: dùng `soxr.ResampleStream` (streaming, giữ trạng thái
   bộ lọc giữa các lần gọi `resample_chunk()`) thay vì `resample()` stateless — đây là lý do
   module này KHÔNG dùng chung `speech.audio.codec.resample()` như mọi nơi khác trong
   codebase, dù cùng dựa trên soxr.
"""

from typing import Optional

import numpy as np

_SILERO_SAMPLE_RATE = 16_000


class SileroVadClassifier:
    """`model_path`: path tới `silero_vad.onnx` (tải từ k2-fsa/sherpa-onnx releases, xem
    `silero_vad_model_path` trong `config/speech.yaml`). `threshold`: xác suất speech tối thiểu
    (0-1) để `is_speech_detected()` trả True — mặc định 0.5 theo model gốc."""

    def __init__(
        self,
        model_path: str,
        *,
        sample_rate: int = 8_000,
        threshold: float = 0.5,
    ) -> None:
        import sherpa_onnx

        self._source_rate = sample_rate
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = model_path
        config.silero_vad.threshold = threshold
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
        self._last_probability = 0.0

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
        speech = self._vad.is_speech_detected()
        self._last_probability = 1.0 if speech else 0.0
        return speech

    @property
    def last_probability(self) -> float:
        """Xấp xỉ nhị phân (0.0/1.0) — sherpa-onnx không expose xác suất thô liên tục qua
        `VoiceActivityDetector`, chỉ `is_speech_detected() -> bool`. Giữ property này để
        khớp interface dự kiến cho Turn Validator (bước 6); nếu cần xác suất liên tục thật,
        cần đổi sang gọi trực tiếp model Silero qua onnxruntime thay vì API bậc cao này."""
        return self._last_probability
