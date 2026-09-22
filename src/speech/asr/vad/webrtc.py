"""VAD dựa trên Google WebRTC's VAD — phân biệt giọng nói với tiếng ồn tốt hơn nhiều
so với EnergyFrameClassifier (RMS đơn thuần không phân biệt được nội dung phổ tần của
giọng nói và noise, khiến tiếng gõ/quạt/hắng giọng bị hiểu nhầm thành turn — bug thật
đã gặp khi test qua LiveKit demo).

Dùng package `webrtcvad-wheels` (không phải `webrtcvad` gốc trên PyPI — bản đó phụ
thuộc `pkg_resources`/setuptools đã bị gỡ khỏi các bản setuptools mới, không cài được
trên môi trường Python hiện đại). Cùng C extension nền tảng (libwebrtc VAD), API giống
hệt nhau.
"""

from speech.asr.vad.streaming import FRAME_MS
from speech.types import SAMPLE_WIDTH_BYTES


class WebRtcVadClassifier:
    """`aggressiveness` 0-3 (webrtcvad): 0 ít nhạy nhất (dễ bỏ sót speech nhỏ), 3 nhạy
    nhất (dễ bắt nhầm noise). Mặc định 2 — cân bằng cho audio narrowband điện thoại."""

    def __init__(self, aggressiveness: int = 2, sample_rate: int = 8_000) -> None:
        import webrtcvad

        if sample_rate not in (8_000, 16_000, 32_000, 48_000):
            raise ValueError(f"webrtcvad không hỗ trợ sample_rate={sample_rate}")
        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        # webrtcvad chỉ chấp nhận frame 10/20/30ms — validate sớm thay vì để C
        # extension raise lỗi mơ hồ ("Error while processing frame") lúc runtime.
        self._expected_frame_bytes = int(sample_rate * FRAME_MS / 1000) * SAMPLE_WIDTH_BYTES

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._expected_frame_bytes:
            return False
        return self._vad.is_speech(frame, self._sample_rate)
