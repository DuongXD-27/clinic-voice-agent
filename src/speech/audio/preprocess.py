"""Tiền xử lý OFFLINE cho nguyên một file audio PCM16 mono: đo mức âm, bỏ DC, gain tĩnh và
tìm các đoạn có giọng. Không dùng cho streaming — mọi hàm nhìn thấy cả file cùng lúc.

Lý do chọn từng kỹ thuật (và các kỹ thuật cố ý không dùng) xem docs/reference/stt-eval-api.md.
"""

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from speech.asr.vad.base import FrameClassifier

_FULL_SCALE = 32768.0
# Frame "có giọng" khi đo mức âm = nằm trong 30 dB so với frame to nhất (như _active_rms của
# eval/noise-bench/bench.py) — không cần VAD, đủ để tính gain trước khi chạy VAD.
_SPEECH_WINDOW_DB = 30.0
_LEVEL_FRAME_MS = 30


@dataclass(frozen=True)
class LevelStats:
    """dBFS: 0 = full scale int16. None khi audio im lặng tuyệt đối."""

    peak_dbfs: Optional[float]
    speech_rms_dbfs: Optional[float]
    clipping_ratio: float


def _samples(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def _to_pcm(samples: np.ndarray) -> bytes:
    return np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()


def _dbfs(amplitude: float) -> Optional[float]:
    return 20 * math.log10(amplitude / _FULL_SCALE) if amplitude > 0 else None


def _frame_rms(samples: np.ndarray, frame: int) -> np.ndarray:
    usable = len(samples) - len(samples) % frame
    if usable == 0:
        return np.sqrt(np.mean(samples**2, keepdims=True)) if samples.size else np.zeros(0)
    return np.sqrt(np.mean(samples[:usable].reshape(-1, frame) ** 2, axis=1))


def measure_level(pcm: bytes, sample_rate: int) -> LevelStats:
    samples = _samples(pcm)
    if samples.size == 0:
        return LevelStats(None, None, 0.0)
    levels = _frame_rms(samples, max(1, sample_rate * _LEVEL_FRAME_MS // 1000))
    loudest = float(levels.max())
    active = levels[levels >= loudest * 10 ** (-_SPEECH_WINDOW_DB / 20)]
    speech_rms = float(np.sqrt(np.mean(active**2))) if loudest > 0 else 0.0
    clipped = np.count_nonzero((samples >= 32767) | (samples <= -32768))
    return LevelStats(
        peak_dbfs=_dbfs(float(np.abs(samples).max())),
        speech_rms_dbfs=_dbfs(speech_rms),
        clipping_ratio=clipped / samples.size,
    )


def remove_dc(pcm: bytes) -> bytes:
    samples = _samples(pcm)
    if samples.size == 0:
        return pcm
    return _to_pcm(samples - samples.mean())


def normalize_gain(
    pcm: bytes,
    stats: LevelStats,
    *,
    quiet_below_dbfs: float = -35.0,
    target_dbfs: float = -26.0,
    max_gain_db: float = 20.0,
    peak_ceiling_dbfs: float = -1.0,
) -> tuple[bytes, float]:
    """Khuếch đại tĩnh (một hằng số cho cả file) CHỈ khi RMS vùng có giọng dưới `quiet_below_dbfs`,
    đưa về gần `target_dbfs` (mức điển hình của audio điện thoại trong golden set).

    File đủ lớn giữ nguyên: đo trên golden set, khuếch đại cả file ở mức bình thường làm WER
    tệ đi nhẹ, còn file nhỏ tiếng thì cải thiện rõ. Gain bị chặn bởi `max_gain_db` (không kéo
    nhiễu nền lên quá mức) và `peak_ceiling_dbfs` (không tự gây clipping).
    """
    if stats.speech_rms_dbfs is None or stats.peak_dbfs is None:
        return pcm, 0.0
    if stats.speech_rms_dbfs >= quiet_below_dbfs:
        return pcm, 0.0
    gain_db = min(
        target_dbfs - stats.speech_rms_dbfs,
        max_gain_db,
        peak_ceiling_dbfs - stats.peak_dbfs,
    )
    if gain_db < 0.5:
        return pcm, 0.0
    return _to_pcm(_samples(pcm) * 10 ** (gain_db / 20)), gain_db


def detect_speech_frames(
    pcm: bytes, sample_rate: int, classifier: FrameClassifier, *, frame_ms: int = 30
) -> list[bool]:
    """Cờ speech cho từng frame liên tiếp (bỏ frame lẻ cuối), đưa vào classifier theo đúng thứ tự
    — Silero là stateful."""
    frame_bytes = sample_rate * frame_ms // 1000 * 2
    return [
        classifier.is_speech(pcm[start : start + frame_bytes])
        for start in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
    ]


def speech_regions(
    flags: list[bool],
    duration_ms: int,
    *,
    frame_ms: int = 30,
    merge_gap_ms: int = 700,
    pad_before_ms: int = 1000,
    pad_after_ms: int = 300,
) -> list[tuple[int, int]]:
    """Gộp cờ speech thành các đoạn (start_ms, end_ms).

    Hai đoạn cách nhau dưới `merge_gap_ms` được coi là cùng một câu. Đệm trước dài hơn đệm sau:
    Silero chỉ bật cờ sau ~250 ms giọng liên tục (min_speech_duration) và bỏ qua hẳn từ ngắn đứng
    trước khoảng ngắt ("Vâng," của golden STT_CF_02 bị bật cờ trễ ~700 ms). Đo trên golden set:
    đệm trước 500 ms cắt mất chữ đầu (WER 0,39 -> 0,41), 1000 ms thì không. Phía sau đã có sẵn
    hangover 500 ms của Silero (min_silence_duration).
    """
    raw: list[tuple[int, int]] = []
    start: Optional[int] = None
    for index, is_speech in enumerate(flags):
        if is_speech and start is None:
            start = index
        elif not is_speech and start is not None:
            raw.append((start * frame_ms, index * frame_ms))
            start = None
    if start is not None:
        raw.append((start * frame_ms, len(flags) * frame_ms))

    regions: list[tuple[int, int]] = []
    previous_end = 0
    for first_ms, last_ms in raw:
        begin = max(0, first_ms - pad_before_ms)
        end = min(duration_ms, last_ms + pad_after_ms)
        # Gộp cả khi phần đệm chồng lên đoạn trước — tránh decode lặp cùng một khúc audio
        if regions and (first_ms - previous_end < merge_gap_ms or begin <= regions[-1][1]):
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((begin, end))
        previous_end = last_ms
    return regions


def split_long_regions(
    regions: list[tuple[int, int]],
    pcm: bytes,
    sample_rate: int,
    *,
    max_ms: int,
    frame_ms: int = 30,
) -> list[tuple[int, int]]:
    """Chia đoạn dài hơn `max_ms` tại frame yên nhất trong nửa sau của mỗi cửa sổ `max_ms`.

    Bộ nhớ decode offline của ZipFormer tăng theo bình phương độ dài (đo: 30 s ~0,6 GB, 90 s
    ~3 GB, 180 s ~12 GB) — một đoạn dài không giới hạn làm OOM cả process server.
    """
    levels = _frame_rms(_samples(pcm), sample_rate * frame_ms // 1000)
    result: list[tuple[int, int]] = []
    for start, end in regions:
        cursor = start
        while end - cursor > max_ms:
            first = (cursor + max_ms // 2) // frame_ms
            last = min((cursor + max_ms) // frame_ms, len(levels))
            if first >= last:
                split = cursor + max_ms
            else:
                split = (first + int(np.argmin(levels[first:last]))) * frame_ms
            result.append((cursor, split))
            cursor = split
        result.append((cursor, end))
    return result


def estimate_snr_db(
    pcm: bytes,
    sample_rate: int,
    flags: list[bool],
    regions: list[tuple[int, int]],
    *,
    frame_ms: int = 30,
) -> Optional[float]:
    """SNR = RMS frame VAD gắn cờ giọng so với RMS frame nằm NGOÀI mọi đoạn (đã đệm).

    Không lấy "frame không gắn cờ" làm nhiễu: Silero bật cờ trễ ~250 ms và bỏ qua từ rất ngắn,
    nên các frame đó vẫn chứa giọng và kéo SNR xuống gần 0 dB. None khi thiếu một trong hai loại
    frame, hoặc nền là im lặng số tuyệt đối (SNR vô hạn).
    """
    if not flags:
        return None
    levels = _frame_rms(_samples(pcm), sample_rate * frame_ms // 1000)[: len(flags)]
    mask = np.array(flags[: len(levels)], dtype=bool)
    outside = np.ones(len(levels), dtype=bool)
    for begin, end in regions:
        outside[begin // frame_ms : -(-end // frame_ms)] = False
    speech, noise = levels[mask], levels[outside]
    if speech.size == 0 or noise.size == 0:
        return None
    speech_rms = float(np.sqrt(np.mean(speech**2)))
    noise_rms = float(np.sqrt(np.mean(noise**2)))
    if noise_rms <= 0 or speech_rms <= 0:
        return None
    return 20 * math.log10(speech_rms / noise_rms)
