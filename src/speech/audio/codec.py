"""Chuẩn hoá mọi nguồn âm thanh về PCM 16-bit mono ở tần số của pipeline (mặc định 8 kHz)."""

import io
import struct
import wave
from dataclasses import dataclass

from speech.audio.g711 import alaw_to_pcm16, mulaw_to_pcm16
from speech.types import CHANNELS, NARROWBAND_RATE, SAMPLE_WIDTH_BYTES, AudioSegment

_FORMAT_PCM = 1
_FORMAT_FLOAT = 3
_FORMAT_ALAW = 6
_FORMAT_MULAW = 7
_FORMAT_EXTENSIBLE = 0xFFFE


@dataclass(frozen=True)
class WavInfo:
    """Thông tin file gốc trước khi downmix/resample, vd format="PCM_24" hoặc "FLOAT_32"."""

    format: str
    channels: int
    sample_rate: int
    bits: int


def decode_wav(data: bytes, target_rate: int = NARROWBAND_RATE) -> AudioSegment:
    """Giải mã wav (xem `read_wav`) rồi resample về `target_rate`."""
    segment, _ = read_wav(data)
    return to_sample_rate(segment, target_rate)


def read_wav(data: bytes) -> tuple[AudioSegment, WavInfo]:
    """PCM 8/16/24/32-bit, float 32/64-bit, G.711 A-law/μ-law, kể cả WAVE_FORMAT_EXTENSIBLE.

    Trả PCM16 mono ở tần số GỐC của file, không resample.
    """
    format_tag, channels, sample_rate, bits, frames = _parse_wav(data)
    if channels < 1 or sample_rate <= 0:
        raise ValueError(f"Header wav không hợp lệ: channels={channels}, rate={sample_rate}")
    name, pcm = _to_pcm16(format_tag, bits, frames, channels)
    if channels != CHANNELS:
        pcm = downmix_to_mono(pcm, channels)
    info = WavInfo(format=name, channels=channels, sample_rate=sample_rate, bits=bits)
    return AudioSegment(pcm=pcm, sample_rate=sample_rate), info


def _to_pcm16(format_tag: int, bits: int, frames: bytes, channels: int) -> tuple[str, bytes]:
    if format_tag == _FORMAT_MULAW:
        return "MULAW", mulaw_to_pcm16(frames)
    if format_tag == _FORMAT_ALAW:
        return "ALAW", alaw_to_pcm16(frames)
    if format_tag == _FORMAT_PCM and bits == 16:
        return "PCM_16", frames[: len(frames) - len(frames) % (2 * channels)]
    if (format_tag, bits) not in {
        (_FORMAT_PCM, 8),
        (_FORMAT_PCM, 24),
        (_FORMAT_PCM, 32),
        (_FORMAT_FLOAT, 32),
        (_FORMAT_FLOAT, 64),
    }:
        raise ValueError(f"Định dạng wav không hỗ trợ: format={format_tag}, bits={bits}")

    import numpy as np

    width = bits // 8
    frames = frames[: len(frames) - len(frames) % (width * channels)]
    if format_tag == _FORMAT_FLOAT:
        samples = np.frombuffer(frames, dtype=np.float32 if bits == 32 else np.float64)
        pcm = np.clip(np.nan_to_num(samples) * 32768.0, -32768, 32767).astype(np.int16)
        return f"FLOAT_{bits}", pcm.tobytes()
    if bits == 8:
        # WAV 8-bit là unsigned, 128 = 0
        pcm = (np.frombuffer(frames, dtype=np.uint8).astype(np.int16) - 128) << 8
    elif bits == 24:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        value = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        value = np.where(value >= 1 << 23, value - (1 << 24), value)
        pcm = (value >> 8).astype(np.int16)
    else:
        pcm = (np.frombuffer(frames, dtype="<i4") >> 16).astype(np.int16)
    return f"PCM_{bits}", pcm.tobytes()


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
    """Resample bằng soxr (polyphase + lowpass FIR chuẩn công nghiệp, tự chống aliasing
    khi hạ tần và không làm méo phổ tần khi nâng tần).

    Trước đây dùng lowpass FIR tay + np.interp (nội suy tuyến tính) — đã xác nhận qua
    benchmark ZipFormer (docs/evidence/zipformer-stt-benchmark.md) rằng nội suy tuyến
    tính khi upsample 8kHz->16kHz làm méo phổ tần đủ để gây lỗi ASR rõ rệt trên tên
    riêng/số liệu (model train ở 16kHz thật, không phải 8kHz nội suy lên). Đổi sang soxr
    sửa được phần lớn các lỗi đó mà không cần đổi model.
    """
    import numpy as np
    import soxr

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return b""
    resampled = soxr.resample(samples, src_rate, dst_rate, quality="HQ")
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


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
            fmt = body
        elif chunk_id == b"data":
            frames = body
        offset += 8 + size + (size & 1)
    if fmt is None or frames is None:
        raise ValueError("wav thiếu chunk fmt hoặc data")
    format_tag, channels, sample_rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if format_tag == _FORMAT_EXTENSIBLE and len(fmt) >= 26:
        # 2 byte đầu của SubFormat GUID (offset 24) chính là format tag thật (PCM/float/...)
        format_tag = struct.unpack("<H", fmt[24:26])[0]
    return format_tag, channels, sample_rate, bits, frames
