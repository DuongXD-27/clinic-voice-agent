"""Theo dõi noise floor liên tục — cung cấp bằng chứng SNR cho Turn Validator/barge-in,
độc lập với quyết định speech/non-speech của VAD (VAD có thể sai trên noise
phòng không đồng đều, xem docs/reference/livekit-architecture.md §5.4).
"""

from collections import deque
from dataclasses import dataclass

import numpy as np

_EPS = 1e-6


@dataclass(frozen=True)
class NoiseEvidence:
    rms: float
    noise_floor: float
    snr_db: float


class NoiseTracker:
    """`floor_alpha`: hệ số EMA cập nhật `noise_floor` — chỉ cập nhật trên frame
    `is_speech=False` để speech thật không tự kéo nền nhiễu ước tính lên cao."""

    def __init__(self, *, floor_alpha: float = 0.05, initial_floor: float = 50.0) -> None:
        self._floor_alpha = floor_alpha
        self._noise_floor = initial_floor

    def observe(self, frame: bytes, is_speech: bool) -> NoiseEvidence:
        """Đo + cập nhật floor trong 1 bước — dùng khi caller không cần tách quyết định
        cập nhật floor khỏi lúc đo (vd. TurnValidator's tracker: is_speech đã CHẮC CHẮN,
        không có bước "REJECT nhưng có thể vẫn là speech thật" ở giữa). `noise_floor` trong
        kết quả trả về là giá trị SAU khi cập nhật (khớp hành vi gốc trước khi tách peek/
        commit_floor) — khác `peek()` luôn trả floor TRƯỚC khi biết caller sẽ quyết định gì."""
        evidence = self.peek(frame)
        if not is_speech:
            self.commit_floor(evidence)
            return self.peek(frame)
        return evidence

    def peek(self, frame: bytes) -> NoiseEvidence:
        """Đo SNR dựa trên `noise_floor` HIỆN TẠI, KHÔNG cập nhật floor — dùng khi caller
        cần biết SNR trước khi tự quyết định is_speech "thật" hay không (frame SNR thấp vẫn
        có thể là speech thật, không nên kéo floor lên vì đoán sai; chỉ khi chắc chắn là nền
        nhiễu mới gọi `commit_floor()` riêng sau đó)."""
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        snr_db = 20.0 * np.log10(max(rms, _EPS) / max(self._noise_floor, _EPS))
        return NoiseEvidence(rms=rms, noise_floor=self._noise_floor, snr_db=float(snr_db))

    def commit_floor(self, evidence: NoiseEvidence) -> None:
        """Cập nhật floor bằng `rms` của 1 `NoiseEvidence` đã đo qua `peek()` — gọi CHỈ khi
        caller đã tự xác nhận chắc chắn đây là nền nhiễu (không phải speech), sau khi có
        đủ bằng chứng để quyết định."""
        self._update_floor(evidence.rms)

    def _update_floor(self, rms: float) -> None:
        self._noise_floor = self._floor_alpha * rms + (1 - self._floor_alpha) * self._noise_floor


class UtteranceEvidenceTracker:
    """SNR của CẢ đoạn nói gần nhất, so với nền nhiễu riêng, cho TurnValidator.

    ASR chỉ phát final sau ~1 s im lặng (hangover Silero + end_silence_ms), nên frame mới
    nhất lúc đó luôn là im lặng, SNR ~0 dB. TurnValidator từng đọc giá trị đó và DROP mọi
    câu trả lời <= 2 từ ("Dạ không", "Có") dù người gọi nói rõ (đo được: rms=1.0, snr=-13.6
    dB cho "DẠ KHÔNG" trên audio sạch). Ở đây tích luỹ năng lượng các frame speech của đoạn
    hiện tại; đoạn mới bắt đầu khi speech quay lại sau `gap_ms`.

    Nền nhiễu KHÔNG lấy từ `NoiseTracker` (EMA cập nhật mọi frame Silero gọi là không-speech):
    Silero báo speech trễ ~250 ms (`min_speech_duration` mặc định của sherpa-onnx), nên phần
    đầu câu — thường to nhất — bị tính thành nhiễu. Bug thật (cuộc gọi 2026-09-26): câu
    "hủy lịch" có floor bị đẩy 145 -> 1337, SNR -3,2 dB, bị DROP; trên 350 đoạn của các bản
    ghi thật, 70 đoạn bị tính < 3 dB dù cả 70 đều to hơn nền 3 s trước đó ít nhất 10 dB. Vì vậy:
    - frame không-speech chỉ vào nền sau `onset_ms`; nếu Silero báo speech trước đó, chúng là
      đầu câu bị nhận trễ và được tính vào năng lượng câu;
    - nền = trung vị `floor_window_ms` frame không-speech gần nhất: vài frame to lọt vào
      không kéo lệch được, nhưng vẫn theo kịp khi nhiễu môi trường tăng thật. Không dùng
      phân vị thấp: nhiễu dao động (giọng nền) sẽ bị đánh giá to hơn nền mọi lúc, mất tác
      dụng chặn ảo giác (eval/noise-bench/validator_snr_eval.py).

    Kết quả chỉ được GIỮ tối đa `hold_ms` sau frame speech cuối — đủ để final tới muộn đọc
    được SNR của câu vừa nói, nhưng không để một ảo giác ASR xuất hiện rất lâu sau (vd. VAD
    chính là WebRTC báo speech trên nhiễu mà Silero không báo) thừa hưởng SNR cao của câu
    thật trước đó. Hết hạn hoặc chưa có đoạn nào thì trả nguyên evidence của frame.
    """

    def __init__(
        self,
        *,
        frame_ms: int = 30,
        gap_ms: int = 600,
        hold_ms: int = 3000,
        onset_ms: int = 300,
        floor_window_ms: int = 3000,
    ) -> None:
        self._gap_frames = max(1, gap_ms // frame_ms)
        self._hold_frames = max(self._gap_frames, hold_ms // frame_ms)
        self._onset_frames = max(0, onset_ms // frame_ms)
        self._pending: deque[float] = deque()
        self._background: deque[float] = deque(maxlen=max(1, floor_window_ms // frame_ms))
        self._power_sum = 0.0
        self._speech_frames = 0
        self._frames_since_speech = self._hold_frames + 1

    def observe(self, evidence: NoiseEvidence, is_speech: bool) -> NoiseEvidence:
        if is_speech:
            if self._frames_since_speech >= self._gap_frames:
                self._power_sum = sum(rms**2 for rms in self._pending)
                self._speech_frames = len(self._pending)
            self._pending.clear()
            self._power_sum += evidence.rms**2
            self._speech_frames += 1
            self._frames_since_speech = 0
        else:
            self._pending.append(evidence.rms)
            if len(self._pending) > self._onset_frames:
                self._background.append(self._pending.popleft())
            self._frames_since_speech += 1
        if not self._speech_frames or self._frames_since_speech > self._hold_frames:
            return evidence
        floor = float(np.median(self._background)) if self._background else evidence.noise_floor
        rms = float(np.sqrt(self._power_sum / self._speech_frames))
        snr_db = 20.0 * np.log10(max(rms, _EPS) / max(floor, _EPS))
        return NoiseEvidence(rms=rms, noise_floor=floor, snr_db=float(snr_db))
