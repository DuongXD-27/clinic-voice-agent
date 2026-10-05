from typing import Iterator

from speech.types import NARROWBAND_RATE, SAMPLE_WIDTH_BYTES

FRAME_MS = 30  # 10/20/30 ms là các khung webrtcvad hỗ trợ ở 8 kHz


def split_frames(
    pcm: bytes, sample_rate: int = NARROWBAND_RATE, frame_ms: int = FRAME_MS
) -> Iterator[bytes]:
    frame_bytes = int(sample_rate * frame_ms / 1000) * SAMPLE_WIDTH_BYTES
    for start in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        yield pcm[start : start + frame_bytes]
