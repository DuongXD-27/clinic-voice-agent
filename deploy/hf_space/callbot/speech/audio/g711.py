"""G.711 μ-law / A-law 8 kHz — mã hoá phổ biến của carrier/SIP (Twilio, Stringee, trunk VN).

Thuần Python (bảng tra 256 phần tử), không cần numpy, chạy được cả Python 3.13
(audioop đã bị gỡ).
"""

import struct


def _mulaw_sample(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    magnitude = ((mantissa << 3) + 0x84) << exponent
    magnitude -= 0x84
    return -magnitude if sign else magnitude


def _alaw_sample(byte: int) -> int:
    byte ^= 0x55
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    if exponent == 0:
        magnitude = (mantissa << 4) + 8
    else:
        magnitude = ((mantissa << 4) + 0x108) << (exponent - 1)
    return magnitude if sign else -magnitude


_MULAW_TABLE = [struct.pack("<h", _mulaw_sample(b)) for b in range(256)]
_ALAW_TABLE = [struct.pack("<h", _alaw_sample(b)) for b in range(256)]


def mulaw_to_pcm16(data: bytes) -> bytes:
    return b"".join(_MULAW_TABLE[b] for b in data)


def alaw_to_pcm16(data: bytes) -> bytes:
    return b"".join(_ALAW_TABLE[b] for b in data)
