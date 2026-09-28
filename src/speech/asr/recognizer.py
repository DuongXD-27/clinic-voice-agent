"""Nối ASR gateway vào miền audio của `speech`: resample về tần số model, trả `Transcript`."""

from typing import AsyncIterator, Protocol

from inference.asr import ASRGateway
from speech.audio.codec import to_sample_rate
from speech.types import AudioSegment, Transcript, TranscriptEvent


class Recognizer(Protocol):
    name: str
    input_sample_rate: int

    def transcribe(self, segment: AudioSegment) -> Transcript: ...


class SpeechRecognizer:
    def __init__(self, gateway: ASRGateway) -> None:
        self._gateway = gateway

    @property
    def name(self) -> str:
        return self._gateway.provider_name

    @property
    def model(self) -> str:
        return self._gateway.model

    @property
    def input_sample_rate(self) -> int:
        return self._gateway.input_sample_rate

    def transcribe(self, segment: AudioSegment) -> Transcript:
        segment = to_sample_rate(segment, self.input_sample_rate)
        result = self._gateway.transcribe(segment.pcm, segment.sample_rate)
        text = result.text.strip()
        return Transcript(text=text, confidence=result.confidence, is_silence=not text)

    def stream(self, frames: AsyncIterator[bytes], **kwargs) -> AsyncIterator[TranscriptEvent]:
        """Ủy quyền xuống `stream()` của provider gốc — method mở rộng ngoài Protocol
        `ASRProvider`/`Recognizer`, chỉ ZipFormer (chunked-offline) hỗ trợ hiện tại.
        Raise rõ ràng nếu provider đang cấu hình không có `stream()`, thay vì lỗi
        `AttributeError` mơ hồ ở nơi gọi."""
        provider = self._gateway.provider
        stream = getattr(provider, "stream", None)
        if stream is None:
            raise RuntimeError(
                f"ASR provider {self._gateway.provider_name!r} không hỗ trợ streaming"
            )
        return stream(frames, **kwargs)
