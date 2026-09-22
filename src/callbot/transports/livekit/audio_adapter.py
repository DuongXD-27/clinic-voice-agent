"""Boundary giữa LiveKit media layer và speech pipeline.

Chỉ làm việc convert format — không quyết định VAD/turn/business logic. LiveKit
`rtc.AudioFrame` mang PCM 16-bit mà `AudioStream` đã tự resample theo `sample_rate`
yêu cầu (xem `rtc.AudioStream.from_track`), nhưng adapter vẫn convert tường minh qua
`AudioSegment`/`to_sample_rate` có sẵn (speech/audio/codec.py) thay vì phụ thuộc ngầm
vào việc SDK resample đúng — nhất quán với mọi nguồn audio khác trong hệ thống.
"""

from typing import TYPE_CHECKING

from speech.audio.codec import to_sample_rate
from speech.types import NARROWBAND_RATE, AudioSegment

if TYPE_CHECKING:
    from livekit import rtc


def livekit_frame_to_segment(
    frame: "rtc.AudioFrame", target_rate: int = NARROWBAND_RATE
) -> AudioSegment:
    """`frame.data` là PCM16 mono/stereo theo `frame.num_channels` — downmix nếu stereo
    trước khi resample, giống `codec.decode_wav` xử lý wav nhiều kênh."""
    pcm = bytes(frame.data)
    if frame.num_channels > 1:
        pcm = _downmix(pcm, frame.num_channels)
    segment = AudioSegment(pcm=pcm, sample_rate=frame.sample_rate)
    return to_sample_rate(segment, target_rate)


def segment_to_livekit_frame(segment: AudioSegment) -> "rtc.AudioFrame":
    """Chiều ngược lại: TTS output (PCM mono) -> rtc.AudioFrame để AudioSource.capture_frame."""
    from livekit import rtc

    samples_per_channel = len(segment.pcm) // 2  # PCM16 = 2 byte/sample
    return rtc.AudioFrame(
        data=segment.pcm,
        sample_rate=segment.sample_rate,
        num_channels=1,
        samples_per_channel=samples_per_channel,
    )


def _downmix(pcm: bytes, channels: int) -> bytes:
    from speech.audio.codec import downmix_to_mono

    return downmix_to_mono(pcm, channels)
