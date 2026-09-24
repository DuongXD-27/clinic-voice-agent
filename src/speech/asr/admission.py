"""Speech Admission — quyết định có đẩy 1 frame vào ASR hay không, dựa trên VAD + duration
+ bằng chứng SNR (NoiseTracker), TRƯỚC khi frame vào `asr_queue` trong `pipeline.py::_fanout()`.

Đây là lớp lọc ĐẦU TIÊN, độc lập với lớp gating nội bộ mà từng ASR provider đã tự làm
(`ZipFormerASR.stream()`/`ElevenLabsRealtimeASR.stream()` đều tự gọi
`silence_classifier.is_speech(frame)` riêng) — không thay thế 2 lớp đó, chỉ giảm tải bằng
cách chặn sớm hơn, dựa trên tín hiệu mạnh hơn (SNR liên tục, không chỉ 1 frame is_speech
đơn lẻ). `vad_queue` KHÔNG bị lọc bởi Admission — VAD cần thấy MỌI frame để tự quyết định
speech_start/speech_end đúng.

`PreRollBuffer`: frame bị REJECT (chưa đủ SNR/duration) vẫn có thể là phần ĐẦU THẬT của
câu nói — ADMIT chỉ xác nhận được sau vài frame (>= min_speech_ms), nên nếu không giữ lại
gì thì ASR luôn mất đúng đoạn đầu câu đã dùng để xác nhận đó (~150-200ms, mẫu đã quan sát
"Không, tôi muốn đổi lịch" mất mất chữ "Không"). Giữ N frame gần nhất trong ring buffer
(deque maxlen); khi REJECT→ADMIT (transition), flush toàn bộ buffer vào `asr_queue` theo
đúng thứ tự trước, rồi mới gửi frame hiện tại — bù lại đúng phần đã "trễ" lúc quyết định.
"""

from collections import deque
from dataclasses import dataclass

from speech.audio.noise_tracker import NoiseEvidence


@dataclass(frozen=True)
class AdmissionDecision:
    admit: bool
    reason: str  # "ok" | "low_snr" | "too_short" | "no_speech"


class SpeechAdmission:
    """Gate SNR + thời lượng; đoạn đã admit giữ thêm im lặng tới endpoint.

    `min_snr_db` áp dụng khi bắt đầu một đoạn speech. Sau khi admit, SNR có thể dao
    động mà không cắt giữa câu; `end_silence_ms` chặn việc đẩy im lặng vào ASR mãi
    mãi khi người dùng đã dứt lời.
    """

    def __init__(
        self,
        *,
        min_snr_db: float = 6.0,
        min_speech_ms: int = 150,
        end_silence_ms: int = 600,
    ) -> None:
        self._min_snr_db = min_snr_db
        self._min_speech_ms = min_speech_ms
        self._end_silence_ms = end_silence_ms

    @property
    def min_snr_db(self) -> float:
        return self._min_snr_db

    def evaluate(
        self,
        *,
        is_speech: bool,
        evidence: NoiseEvidence,
        speech_ms_so_far: float,
        already_admitted: bool,
        nonspeech_ms_so_far: float = 0.0,
    ) -> AdmissionDecision:
        if already_admitted:
            if not is_speech and nonspeech_ms_so_far >= self._end_silence_ms:
                return AdmissionDecision(admit=False, reason="no_speech")
            return AdmissionDecision(admit=True, reason="ok")
        if not is_speech:
            return AdmissionDecision(admit=False, reason="no_speech")
        if evidence.snr_db < self._min_snr_db:
            return AdmissionDecision(admit=False, reason="low_snr")
        if speech_ms_so_far < self._min_speech_ms:
            return AdmissionDecision(admit=False, reason="too_short")
        return AdmissionDecision(admit=True, reason="ok")


class PreRollBuffer:
    """Ring buffer giữ N frame gần nhất trong lúc Admission chưa ADMIT — xem docstring
    module. `maxlen_frames`: dung lượng buffer; caller (`pipeline.py::_fanout()`) tính từ
    `pre_roll_ms // frame_ms` để cấu hình theo thời gian thay vì số frame cố định."""

    def __init__(self, maxlen_frames: int) -> None:
        if maxlen_frames <= 0:
            raise ValueError("maxlen_frames phải lớn hơn 0")
        self._buffer: "deque[bytes]" = deque(maxlen=maxlen_frames)

    def push(self, frame: bytes) -> None:
        """Gọi khi frame KHÔNG được admit — giữ lại phòng khi ADMIT xảy ra ngay sau đó."""
        self._buffer.append(frame)

    def flush(self) -> list[bytes]:
        """Trả toàn bộ frame đang giữ theo đúng thứ tự thời gian rồi làm rỗng buffer —
        gọi đúng 1 lần tại thời điểm REJECT→ADMIT, TRƯỚC khi gửi frame hiện tại."""
        frames = list(self._buffer)
        self._buffer.clear()
        return frames

    def clear(self) -> None:
        """Gọi khi candidate bị huỷ hẳn (vd. quay lại no_speech kéo dài) — không để frame
        noise cũ lẫn vào lần ADMIT kế tiếp, không liên quan lần speech này nữa."""
        self._buffer.clear()
