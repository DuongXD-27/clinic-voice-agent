from dataclasses import dataclass

import pytest

from callbot.transports.livekit.audio_adapter import (
    livekit_frame_to_segment,
    segment_to_livekit_frame,
)
from speech.types import NARROWBAND_RATE, AudioSegment


@dataclass
class _FakeAudioFrame:
    """Giả lập đúng field mà livekit_frame_to_segment dùng — không cần SDK livekit thật."""

    data: bytes
    sample_rate: int
    num_channels: int


def test_livekit_frame_to_segment_resamples_to_narrowband() -> None:
    # 48kHz mono, 0.1s toàn giá trị cố định — không cần âm thanh thật, chỉ test convert.
    pcm = (b"\x10\x20") * 4800
    frame = _FakeAudioFrame(data=pcm, sample_rate=48000, num_channels=1)

    segment = livekit_frame_to_segment(frame, target_rate=NARROWBAND_RATE)

    assert segment.sample_rate == NARROWBAND_RATE
    assert len(segment.pcm) > 0


def test_livekit_frame_to_segment_downmixes_stereo() -> None:
    pytest.importorskip("numpy")
    # Stereo interleaved L/R, mỗi sample 2 byte -> 1 frame stereo = 4 byte.
    pcm = (b"\x00\x10" + b"\x00\x10") * 100  # L=R=hằng số -> downmix giữ nguyên giá trị
    frame = _FakeAudioFrame(data=pcm, sample_rate=8000, num_channels=2)

    segment = livekit_frame_to_segment(frame, target_rate=NARROWBAND_RATE)

    assert segment.sample_rate == NARROWBAND_RATE
    # Downmix 2 kênh giống hệt nhau -> số sample giảm 1 nửa so với bytes gốc / channels.
    assert len(segment.pcm) == 100 * 2


def test_livekit_frame_to_segment_passthrough_when_already_target_rate() -> None:
    pcm = b"\x00\x10" * 80
    frame = _FakeAudioFrame(data=pcm, sample_rate=NARROWBAND_RATE, num_channels=1)

    segment = livekit_frame_to_segment(frame, target_rate=NARROWBAND_RATE)

    assert segment.pcm == pcm


def test_segment_to_livekit_frame_roundtrip_fields() -> None:
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-agents/rtc")
    pcm = b"\x00\x10" * 80
    segment = AudioSegment(pcm=pcm, sample_rate=24000)

    frame = segment_to_livekit_frame(segment)

    assert bytes(frame.data) == pcm
    assert frame.sample_rate == 24000
    assert frame.num_channels == 1
    assert frame.samples_per_channel == 80


if __name__ == "__main__":
    pytest.main([__file__])
