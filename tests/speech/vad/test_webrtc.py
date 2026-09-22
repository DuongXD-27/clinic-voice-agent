import math
import struct

import pytest

pytest.importorskip("webrtcvad", reason="cần extra [vad-webrtc] cài webrtcvad-wheels")

from speech.asr.vad.streaming import FRAME_MS  # noqa: E402
from speech.asr.vad.webrtc import WebRtcVadClassifier  # noqa: E402

_SAMPLE_RATE = 8_000
_FRAME_BYTES = int(_SAMPLE_RATE * FRAME_MS / 1000) * 2


def _silence() -> bytes:
    return b"\x00\x00" * (_FRAME_BYTES // 2)


def _tone(freq_hz: float = 300.0, amplitude: int = 8000) -> bytes:
    count = _FRAME_BYTES // 2
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq_hz * i / _SAMPLE_RATE)))
        for i in range(count)
    )


def test_silence_is_not_speech() -> None:
    classifier = WebRtcVadClassifier(sample_rate=_SAMPLE_RATE)
    assert classifier.is_speech(_silence()) is False


def test_voice_like_tone_is_speech() -> None:
    classifier = WebRtcVadClassifier(sample_rate=_SAMPLE_RATE)
    assert classifier.is_speech(_tone()) is True


def test_wrong_frame_length_is_not_speech_not_error() -> None:
    """Frame sai độ dài (khác 30ms @ 8kHz) phải trả False thay vì để C extension raise
    lỗi mơ hồ — validate sớm ở tầng Python (xem docstring WebRtcVadClassifier)."""
    classifier = WebRtcVadClassifier(sample_rate=_SAMPLE_RATE)
    assert classifier.is_speech(b"\x00\x00" * 10) is False


def test_rejects_unsupported_sample_rate() -> None:
    with pytest.raises(ValueError):
        WebRtcVadClassifier(sample_rate=11_025)


@pytest.mark.parametrize("aggressiveness", [0, 1, 2, 3])
def test_all_aggressiveness_levels_accept_clear_tone(aggressiveness: int) -> None:
    classifier = WebRtcVadClassifier(aggressiveness=aggressiveness, sample_rate=_SAMPLE_RATE)
    assert classifier.is_speech(_tone(amplitude=16000)) is True


if __name__ == "__main__":
    pytest.main([__file__])
