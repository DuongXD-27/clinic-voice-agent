"""Bằng chứng cho TurnValidator và InterruptionController, gom một chỗ.

- SNR theo frame (NoiseTracker): theo dõi nền nhiễu.
- SNR của cả câu vừa nói (UtteranceEvidenceTracker): cho TurnValidator và ngắt lời. ASR
  trả kết quả bất đồng bộ; frame mới nhất khi ấy có thể đã là im lặng.
- Độ ổn định transcript (TranscriptEvidenceTracker): hội tụ hay dao động (dấu hiệu ảo giác).

`noise_classifier` phải là Silero: WebRTC/energy báo speech gần như liên tục trên nhiễu phòng,
nền nhiễu không cập nhật được và SNR sai.
"""

from typing import Optional

from speech.asr.evidence import StabilityVerdict, TranscriptEvidenceTracker
from speech.asr.vad.base import FrameClassifier
from speech.audio.noise_tracker import NoiseEvidence, NoiseTracker, UtteranceEvidenceTracker
from speech.types import TranscriptEvent


class TurnEvidence:
    def __init__(
        self,
        noise_classifier: FrameClassifier,
        *,
        frame_ms: int,
        transcript: Optional[TranscriptEvidenceTracker] = None,
        noise: Optional[NoiseTracker] = None,
    ) -> None:
        self._noise_classifier = noise_classifier
        self._transcript = transcript or TranscriptEvidenceTracker()
        self._noise = noise or NoiseTracker()
        # Các cửa sổ của tracker tính bằng frame: phải biết frame dài bao nhiêu ms.
        self._utterance = UtteranceEvidenceTracker(frame_ms=frame_ms)
        self.frame_noise: Optional[NoiseEvidence] = None
        self.utterance_noise: Optional[NoiseEvidence] = None

    def observe_frame(self, frame: bytes, *, level_frame: Optional[bytes] = None) -> None:
        """Gọi cho MỌI frame theo thứ tự tới, kể cả lúc bot đang nói. `level_frame`: cùng đoạn
        PCM trước khi tăng âm (`QuietSpeechGain`) — SNR là tỉ số nên phải đo trên một thang: nền
        (trung vị vài giây im lặng) đo ở hệ số cũ, câu mới ở hệ số mới thì SNR lệch đúng bằng
        bước nhảy hệ số. `frame` vẫn là thứ đưa cho bộ phân loại (tra kết quả theo đối tượng)."""
        is_speech = self._noise_classifier.is_speech(frame)
        self.frame_noise = self._noise.observe(level_frame or frame, is_speech)
        self.utterance_noise = self._utterance.observe(self.frame_noise, is_speech)

    def observe_transcript(self, event: TranscriptEvent) -> StabilityVerdict:
        verdict = self._transcript.observe(event)
        if event.is_final:
            # Độ ổn định chỉ xét bên trong một câu: không reset thì chuỗi trả lời thật
            # "vâng" -> "có" -> "vâng" khớp mẫu dao động và câu thứ ba bị DROP.
            self._transcript.reset()
        return verdict

    def reset_transcript(self) -> None:
        """Đoạn ASR đang mở bị bỏ (không có final): bắt đầu lại độ ổn định cho đoạn sau."""
        self._transcript.reset()
