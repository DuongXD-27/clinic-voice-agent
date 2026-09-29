import struct

import numpy as np
import pytest

from speech.audio.codec import decode_wav, read_wav

# Phần sau 2 byte format tag của SubFormat GUID chuẩn (KSDATAFORMAT_SUBTYPE_*)
_GUID_TAIL = b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"


def _wav(
    format_tag: int,
    rate: int,
    bits: int,
    frames: bytes,
    channels: int = 1,
    subformat: int | None = None,
) -> bytes:
    block_align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", format_tag, channels, rate, rate * block_align, block_align, bits)
    if subformat is not None:
        fmt += struct.pack("<HHI", 22, bits, 0) + struct.pack("<H", subformat) + _GUID_TAIL
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(frames)) + frames
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _int16(pcm: bytes) -> list[int]:
    return np.frombuffer(pcm, dtype=np.int16).tolist()


def _pcm24(values: list[int]) -> bytes:
    return b"".join(value.to_bytes(3, "little", signed=True) for value in values)


def test_pcm16_stereo_keeps_native_rate_and_downmixes() -> None:
    frames = np.array([1000, 3000, -2000, -4000], dtype="<i2").tobytes()
    segment, info = read_wav(_wav(1, 44_100, 16, frames, channels=2))

    assert segment.sample_rate == 44_100
    assert _int16(segment.pcm) == [2000, -3000]
    assert (info.format, info.channels, info.sample_rate, info.bits) == ("PCM_16", 2, 44_100, 16)


def test_pcm24_is_scaled_to_int16() -> None:
    segment, info = read_wav(_wav(1, 16_000, 24, _pcm24([8_388_607, -8_388_608, 100 * 256, -1])))

    assert info.format == "PCM_24"
    assert _int16(segment.pcm) == [32767, -32768, 100, -1]


def test_pcm32_and_pcm8() -> None:
    pcm32 = np.array([7 * 65536, -3 * 65536], dtype="<i4").tobytes()
    assert _int16(read_wav(_wav(1, 16_000, 32, pcm32))[0].pcm) == [7, -3]
    assert _int16(read_wav(_wav(1, 8_000, 8, bytes([128, 0, 255])))[0].pcm) == [0, -32768, 32512]


def test_float32_is_clipped_to_int16() -> None:
    frames = np.array([0.5, -1.0, 1.5], dtype="<f4").tobytes()
    segment, info = read_wav(_wav(3, 48_000, 32, frames))

    assert info.format == "FLOAT_32"
    assert _int16(segment.pcm) == [16384, -32768, 32767]


def test_extensible_uses_subformat_tag() -> None:
    wav = _wav(0xFFFE, 16_000, 24, _pcm24([256, -256]), subformat=1)
    segment, info = read_wav(wav)

    assert info.format == "PCM_24"
    assert _int16(segment.pcm) == [1, -1]


def test_decode_wav_still_resamples_new_formats() -> None:
    frames = np.zeros(1600, dtype="<f4").tobytes()
    segment = decode_wav(_wav(3, 16_000, 32, frames), target_rate=8_000)

    assert segment.sample_rate == 8_000
    assert len(segment.pcm) == 800 * 2


def test_unsupported_format_raises() -> None:
    with pytest.raises(ValueError, match="không hỗ trợ"):
        read_wav(_wav(2, 8_000, 4, b"\x00" * 10))
