from typing import Iterable, Iterator

from callbot.speech.types import NARROWBAND_RATE, SAMPLE_WIDTH_BYTES, VadEvent
from callbot.speech.vad.base import FrameClassifier

FRAME_MS = 30  # 10/20/30 ms là các khung webrtcvad hỗ trợ ở 8 kHz


def split_frames(
    pcm: bytes, sample_rate: int = NARROWBAND_RATE, frame_ms: int = FRAME_MS
) -> Iterator[bytes]:
    frame_bytes = int(sample_rate * frame_ms / 1000) * SAMPLE_WIDTH_BYTES
    for start in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        yield pcm[start : start + frame_bytes]


class StreamingVAD:
    """Gom frame thành đoạn nói; phát speech_end sau `end_silence_ms` im lặng."""

    def __init__(self, classifier: FrameClassifier, end_silence_ms: int = 600) -> None:
        self._classifier = classifier
        self._end_silence_frames = max(1, end_silence_ms // FRAME_MS)

    def process(self, frames: Iterable[bytes]) -> Iterator[VadEvent]:
        in_speech = False
        silent_frames = 0
        for frame in frames:
            if self._classifier.is_speech(frame):
                if not in_speech:
                    in_speech = True
                    yield VadEvent("speech_start")
                silent_frames = 0
                yield VadEvent("speech", frame)
            elif in_speech:
                silent_frames += 1
                if silent_frames >= self._end_silence_frames:
                    in_speech = False
                    yield VadEvent("speech_end")
        if in_speech:
            yield VadEvent("speech_end")
