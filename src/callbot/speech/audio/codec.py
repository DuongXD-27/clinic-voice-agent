"""Chuẩn hoá mọi nguồn âm thanh về PCM 16-bit mono ở tần số của pipeline (mặc định 8 kHz)."""

import io
import struct
import wave

from callbot.speech.audio.g711 import alaw_to_pcm16, mulaw_to_pcm16
from callbot.speech.types import CHANNELS, NARROWBAND_RATE, SAMPLE_WIDTH_BYTES, AudioSegment

_FORMAT_PCM = 1
_FORMAT_ALAW = 6
_FORMAT_MULAW = 7


def decode_wav(data: bytes, target_rate: int = NARROWBAND_RATE) -> AudioSegment:
    """Hỗ trợ wav PCM 16-bit, G.711 A-law và μ-law; tự downmix và resample."""
    format_tag, channels, sample_rate, bits, frames = _parse_wav(data)

    if format_tag == _FORMAT_MULAW:
        pcm = mulaw_to_pcm16(frames)
    elif format_tag == _FORMAT_ALAW:
        pcm = alaw_to_pcm16(frames)
    elif format_tag == _FORMAT_PCM and bits == 16:
        pcm = frames
    else:
        raise ValueError(f"Định dạng wav không hỗ trợ: format={format_tag}, bits={bits}")

    if channels != CHANNELS:
        pcm = downmix_to_mono(pcm, channels)
    if sample_rate != target_rate:
        pcm = resample(pcm, sample_rate, target_rate)
    return AudioSegment(pcm=pcm, sample_rate=target_rate)


def encode_wav(segment: AudioSegment) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav.setframerate(segment.sample_rate)
        wav.writeframes(segment.pcm)
    return buffer.getvalue()


def to_sample_rate(segment: AudioSegment, target_rate: int) -> AudioSegment:
    if segment.sample_rate == target_rate:
        return segment
    return AudioSegment(
        pcm=resample(segment.pcm, segment.sample_rate, target_rate), sample_rate=target_rate
    )


def downmix_to_mono(pcm: bytes, channels: int) -> bytes:
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).reshape(-1, channels)
    return samples.mean(axis=1).astype(np.int16).tobytes()


def resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample có lọc thông thấp khi hạ tần số (16k -> 8k), tránh aliasing trên dải thoại."""
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return b""
    if dst_rate < src_rate:
        samples = _lowpass(samples, cutoff_hz=dst_rate / 2 * 0.9, rate=src_rate)
    # TODO: thay bằng soxr nếu cần chất lượng cao hơn khi đo WER
    dst_len = int(samples.size * dst_rate / src_rate)
    src_x = np.linspace(0, samples.size - 1, num=dst_len)
    resampled = np.interp(src_x, np.arange(samples.size), samples)
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


def _lowpass(samples, cutoff_hz: float, rate: int, taps: int = 63):
    import numpy as np

    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff_hz / rate * n) * np.hamming(taps)
    kernel /= kernel.sum()
    return np.convolve(samples, kernel, mode="same")


def _parse_wav(data: bytes) -> tuple[int, int, int, int, bytes]:
    """Đọc header RIFF thủ công — module `wave` không đọc được G.711."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Không phải file wav")
    fmt = None
    frames = None
    offset = 12
    while offset + 8 <= len(data):
        chunk_id, size = struct.unpack("<4sI", data[offset : offset + 8])
        body = data[offset + 8 : offset + 8 + size]
        if chunk_id == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk_id == b"data":
            frames = body
        offset += 8 + size + (size & 1)
    if fmt is None or frames is None:
        raise ValueError("wav thiếu chunk fmt hoặc data")
    format_tag, channels, sample_rate, _, _, bits = fmt
    return format_tag, channels, sample_rate, bits, frames
