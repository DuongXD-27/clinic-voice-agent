"""VAD cho audio đến real-time (LiveKit track), không có sẵn trong bộ nhớ.

`async for` để không chặn event loop khi frame đến chậm hơn thời gian xử lý.
"""

from typing import AsyncIterator

from speech.asr.vad.base import FrameClassifier, VadEvent
from speech.asr.vad.streaming import FRAME_MS


class AsyncStreamingVAD:
    """Gom frame thành đoạn nói; phát speech_end sau `end_silence_ms` im lặng."""

    def __init__(self, classifier: FrameClassifier, end_silence_ms: int = 600) -> None:
        self._classifier = classifier
        self._end_silence_frames = max(1, end_silence_ms // FRAME_MS)

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        in_speech = False
        silent_frames = 0
        async for frame in frames:
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
