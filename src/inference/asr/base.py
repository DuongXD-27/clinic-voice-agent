from typing import AsyncIterator, Protocol

from callbot.speech.types import AudioSegment, Transcript, TranscriptEvent


class ASRProvider(Protocol):
    name: str
    # Tần số model cần; provider tự resample từ audio băng hẹp của pipeline nếu khác
    input_sample_rate: int

    def transcribe(self, segment: AudioSegment) -> Transcript:
        """Nhận dạng trọn một lượt nói — đường chấm điểm qua HTTP."""
        ...

    def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        """Nhận dạng streaming, trả partial + final — phone leg tuần 6."""
        ...
