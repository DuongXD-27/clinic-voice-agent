"""Tăng âm giọng người gọi quá nhỏ trên luồng streaming (LiveKit), không kéo nhiễu nền lên.

Silero (VAD chính và bộ chốt câu của ASR) phụ thuộc mức âm tuyệt đối: giọng web ở -20 dBFS nhận ra
99,8% frame, -45 dBFS còn 78%, -50 dBFS 42%, -55 dBFS 17% — người nói xa mic / mic nhỏ mất cả lượt.
Nhiễu văn phòng thuần thì Silero không báo nhầm frame nào tới -45 dBFS, báo nhầm ~2% từ -40 dBFS
(đo 11/10, docs/evidence/livekit-quiet-speech-gain-2026-10-11.md).

Cùng ngưỡng với `normalize_gain` của đường HTTP (giọng dưới -35 dBFS mới tăng, đưa về -26 dBFS, tối
đa +20 dB), nhưng streaming không thấy trước cả câu nên:
- Mức giọng: giữ mức (RMS, đo TRƯỚC khi tăng) của đoạn nói to nhất gần đây, giảm rất chậm
  (`_HOLD_DECAY_DB_PER_S`). Đoạn nói = các frame Silero gắn cờ tiếng nói, không tính lúc bot đang nói
  và `_AFTER_BOT_GUARD_S` ngay sau đó (tiếng bot vọng lại, dư âm phòng — dump cuộc gọi web thật: đoạn
  Silero gắn cờ ở -40..-60 dBFS lúc bot chào, tính vào thì câu đầu của người gọi bị tăng 15-20 dB).
  Chỉ tăng khi MỌI giọng nghe được đều nhỏ: cuộc gọi thật có TV /
  người khác nói nhỏ phía sau ("THANH THỦY ĐÂY LÀ SÓNG TRUYỀN HÌNH TRỰC TIẾP…", log 09/10) — lấy
  trung bình các frame gần đây thì người gọi im một lúc là mức trôi xuống mức TV và TV được tăng âm.
- Nền nhiễu: phân vị 90 mức các frame KHÔNG có tiếng nói trong ~10 s gần nhất (cả lúc bot nói:
  tiếng vọng còn sót làm nền lên). Hệ số không bao giờ đưa nền lên quá `_MAX_FLOOR_DBFS` — nền nhiễu
  (quạt, TV, tiếng vọng) càng to thì càng ít tăng; tăng âm không làm SNR tốt lên nên nền đã to thì
  tăng chỉ thêm báo nhầm. Không dùng trung vị: nhiễu văn phòng đến từng cụm (gõ phím, người nói xa),
  đỉnh cụm cao hơn trung vị ~12 dB và chính đỉnh cụm làm Silero báo nhầm — giới hạn theo trung vị
  để lọt lượt giả "ĐÂY" trên đoạn chỉ có nhiễu (đo 11/10). Không dùng RMS: một tiếng gõ / va chạm
  máy ngắn (< 10% frame) đủ kéo RMS lên và hệ số tụt giữa cuộc gọi.
- Giọng đủ to (>= `_QUIET_BELOW_DBFS`): hệ số 0 dB, luồng giữ nguyên từng byte — đa số cuộc gọi web
  đã qua AGC trình duyệt, thêm AGC server ở mức thường làm WER lượt 0,095 -> 0,179 (đo 30/09).
- Hệ số chỉ đổi sau `_APPLY_AFTER_SILENCE_S` im lặng liên tục (giữ nguyên suốt một câu) và KHÔNG
  giảm chỉ vì người gọi nói to hơn: Silero "nhớ" mức âm — sau một câu to hơn 6 / 10 / 14 dB, câu kế
  tiếp bị nhận trễ 0,3 s / 1,9 s / bỏ sót hẳn (đo 11/10). Hệ số chỉ giảm khi nền nhiễu lên (giới hạn
  nền) hoặc giọng đã tăng tới mức to quá `_MAX_SPEECH_DBFS`. Xoá trạng thái Silero lúc im lặng thay
  cho việc này đã thử và loại: Silero cũng thích nghi với im lặng nên nhạy hơn với giọng nhỏ, xoá
  trạng thái làm câu nhỏ bị bỏ sót nhiều hơn. Từ ngưỡng bật tới mức tăng đủ có một đoạn chuyển
  `_KNEE_DB` để hệ số không nhảy 0 -> +9 dB khi mức giọng chạm ngưỡng.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_FULL_SCALE = 32768.0
# Như `speech.audio.preprocess.normalize_gain` (đường HTTP /v1/calls, /v1/stt).
_QUIET_BELOW_DBFS = -35.0
_TARGET_DBFS = -26.0
_MAX_GAIN_DB = 20.0
_KNEE_DB = 5.0
# Nền nhiễu sau khi tăng (phân vị 90, xem `floor_dbfs`) không vượt mức này: Silero không báo nhầm
# frame nào trên nhiễu văn phòng có RMS tới -45 dBFS, báo nhầm ~2% từ -40 dBFS; với nhiễu này phân vị
# 90 xấp xỉ RMS.
_MAX_FLOOR_DBFS = -50.0
# Đoạn nói: các frame tiếng nói người gọi, cho phép ngắt <= `_RUN_MAX_GAP_FRAMES` frame (Silero chập
# chờn), tính mức khi đã dài >= `_MIN_RUN_FRAMES` frame (0,3 s — không tính tiếng gõ, ho ngắn).
_RUN_MAX_GAP_FRAMES = 5
_MIN_RUN_FRAMES = 10
# Mức đoạn nói to nhất giảm 3 dB mỗi phút: người gọi đổi tư thế (cầm máy xa ra) thì vài phút sau mới
# được tăng, đổi lại tiếng nhỏ hơn phía sau không kéo được hệ số lên.
_HOLD_DECAY_DB_PER_S = 0.05
# Nền nhiễu: phân vị 90 mức các frame không có tiếng nói trong ~10 s (333 frame 30 ms) gần nhất.
_FLOOR_PERCENTILE = 90
_FLOOR_FRAMES_KEPT = 333
_MIN_FLOOR_FRAMES = 33
# Hệ số chỉ đổi khi đã im lặng liên tục chừng này.
_APPLY_AFTER_SILENCE_S = 1.0
# Không tính là giọng người gọi chừng này sau khi bot dứt lời (như `turn_post_bot_guard_ms`).
_AFTER_BOT_GUARD_S = 0.5
# Đoạn nói to nhất sau khi tăng không vượt mức này (RMS): người gọi từ nói nhỏ chuyển sang nói to thì
# giảm hệ số, không để bộ chặn đỉnh nén giọng liên tục.
_MAX_SPEECH_DBFS = -12.0
# Đỉnh mẫu sau khi tăng không vượt mức này (không tự gây cắt đỉnh).
_PEAK_CEILING = _FULL_SCALE * 10 ** (-1.0 / 20)
# Ghi log khi hệ số đổi chừng này dB so với lần ghi trước.
_LOG_STEP_DB = 3.0


def frame_dbfs(pcm: bytes) -> float:
    """RMS frame PCM16, dBFS (im lặng số = -120)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if not samples.size:
        return -120.0
    power = float(np.mean(samples * samples))
    return 10 * math.log10(power / _FULL_SCALE**2) if power > 0 else -120.0


class QuietSpeechGain:
    """Một instance cho một cuộc gọi. `STTPipeline` gọi cho MỌI frame theo đúng thứ tự:
    `apply(frame)` (trả frame đã tăng theo hệ số hiện tại) rồi `observe(is_speech, bot_speaking)`
    với quyết định của bộ phân loại dùng chung trên chính frame đã tăng."""

    def __init__(self, *, frame_ms: int) -> None:
        self._frame_s = frame_ms / 1000
        self._apply_after_frames = max(1, round(_APPLY_AFTER_SILENCE_S / self._frame_s))
        self._after_bot_frames = round(_AFTER_BOT_GUARD_S / self._frame_s)
        self._frames_since_bot = self._after_bot_frames
        self._gain_db = 0.0
        self._last_dbfs = -120.0
        self._quiet_dbfs: deque[float] = deque(maxlen=_FLOOR_FRAMES_KEPT)
        self._silent_frames = 0
        # Đoạn nói đang nghe: tổng công suất (tỉ lệ full scale), số frame tiếng nói, số frame ngắt.
        self._run_power = 0.0
        self._run_frames = 0
        self._run_gap = 0
        self._held_dbfs: Optional[float] = None
        self._logged_gain_db = 0.0

    @property
    def gain_db(self) -> float:
        return self._gain_db

    def apply(self, frame: bytes) -> bytes:
        """Frame sau khi nhân hệ số hiện tại; 0 dB thì trả nguyên đối tượng frame."""
        self._last_dbfs = frame_dbfs(frame)
        if self._gain_db <= 0.0:
            return frame
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
        factor = 10 ** (self._gain_db / 20)
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        if peak * factor > _PEAK_CEILING:
            factor = max(1.0, _PEAK_CEILING / peak)
        return np.clip(np.round(samples * factor), -32768, 32767).astype(np.int16).tobytes()

    def observe(self, is_speech: bool, *, bot_speaking: bool = False) -> None:
        """Cập nhật mức giọng / nền nhiễu bằng mức TRƯỚC khi tăng của frame vừa `apply`; đã im
        lặng đủ lâu thì đặt hệ số theo mục tiêu."""
        self._frames_since_bot = 0 if bot_speaking else self._frames_since_bot + 1
        self._track_run(is_speech and self._frames_since_bot > self._after_bot_frames)
        if is_speech:
            self._silent_frames = 0
            return
        self._quiet_dbfs.append(self._last_dbfs)
        self._silent_frames += 1
        if self._silent_frames < self._apply_after_frames:
            return
        self._gain_db = min(max(self._gain_db, self._target_db()), self._cap_db())
        if abs(self._gain_db - self._logged_gain_db) >= _LOG_STEP_DB or (
            self._gain_db == 0.0 < self._logged_gain_db
        ):
            self._logged_gain_db = self._gain_db
            logger.info(
                "quiet_gain: gain=%+.1f dB speech=%s dBFS floor=%s dBFS",
                self._gain_db,
                _fmt(self.speech_dbfs()),
                _fmt(self.floor_dbfs()),
            )

    def _track_run(self, caller_speech: bool) -> None:
        if self._held_dbfs is not None:
            self._held_dbfs -= _HOLD_DECAY_DB_PER_S * self._frame_s
        if caller_speech:
            self._run_power += 10 ** (self._last_dbfs / 10)
            self._run_frames += 1
            self._run_gap = 0
        elif self._run_frames:
            self._run_gap += 1
            if self._run_gap > _RUN_MAX_GAP_FRAMES:
                self._run_power, self._run_frames, self._run_gap = 0.0, 0, 0
            return
        if self._run_frames >= _MIN_RUN_FRAMES:
            level = 10 * math.log10(self._run_power / self._run_frames)
            if self._held_dbfs is None or level > self._held_dbfs:
                self._held_dbfs = level

    def speech_dbfs(self) -> Optional[float]:
        """Mức (RMS) đoạn nói to nhất gần đây của người gọi, đã giảm dần; None khi chưa có đoạn nào."""
        return self._held_dbfs

    def floor_dbfs(self) -> Optional[float]:
        """Phân vị 90 mức các frame không có tiếng nói gần đây; None khi chưa đủ."""
        if len(self._quiet_dbfs) < _MIN_FLOOR_FRAMES:
            return None
        return float(np.percentile(np.array(self._quiet_dbfs), _FLOOR_PERCENTILE))

    def _target_db(self) -> float:
        """Hệ số muốn có theo mức giọng hiện tại (0 khi giọng đủ to)."""
        speech = self.speech_dbfs()
        if speech is None or speech >= _QUIET_BELOW_DBFS:
            return 0.0
        knee = min(1.0, (_QUIET_BELOW_DBFS - speech) / _KNEE_DB)
        return min(knee * (_TARGET_DBFS - speech), _MAX_GAIN_DB)

    def _cap_db(self) -> float:
        """Hệ số tối đa được phép lúc này: nền nhiễu sau khi tăng <= `_MAX_FLOOR_DBFS`, đoạn nói to
        nhất sau khi tăng <= `_MAX_SPEECH_DBFS`. Chưa đo được nền thì không tăng."""
        speech, floor = self.speech_dbfs(), self.floor_dbfs()
        if floor is None:
            return 0.0
        cap = _MAX_FLOOR_DBFS - floor
        if speech is not None:
            cap = min(cap, _MAX_SPEECH_DBFS - speech)
        return max(0.0, cap)


def _fmt(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.1f}"
