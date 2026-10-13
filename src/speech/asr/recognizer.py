"""Nối ASR gateway vào miền audio của `speech`: resample về tần số model, trả `Transcript`."""

from typing import AsyncIterator, Protocol

from inference.asr import ASRGateway
from speech.asr.stream_context import StreamingFrame
from speech.audio.codec import to_sample_rate
from speech.types import AsrSegmentEnd, AudioSegment, Transcript, TranscriptEvent


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

    @property
    def supports_stream_context(self) -> bool:
        return getattr(self._gateway.provider, "supports_stream_context", False)

    @property
    def supports_hotwords(self) -> bool:
        return getattr(self._gateway.provider, "supports_hotwords", False)

    @property
    def supports_nbest(self) -> bool:
        return getattr(self._gateway.provider, "supports_nbest", False)

    @property
    def supports_preroll_frames(self) -> bool:
        return getattr(self._gateway.provider, "supports_preroll_frames", False)

    @property
    def supports_segment_finalize(self) -> bool:
        return getattr(self._gateway.provider, "supports_segment_finalize", False)

    def warm_up(self) -> None:
        """Nạp trước phần model provider chỉ nạp khi cần (vd. ZipFormer: beam/hotword, top N)."""
        warm = getattr(self._gateway.provider, "warm_up", None)
        if callable(warm):
            warm()

    def transcribe(self, segment: AudioSegment) -> Transcript:
        segment = to_sample_rate(segment, self.input_sample_rate)
        result = self._gateway.transcribe(segment.pcm, segment.sample_rate)
        text = result.text.strip()
        return Transcript(text=text, confidence=result.confidence, is_silence=not text)

    def stream(
        self, frames: AsyncIterator[bytes | StreamingFrame | AsrSegmentEnd], **kwargs
    ) -> AsyncIterator[TranscriptEvent]:
        """Ủy quyền xuống `stream()` của provider gốc — method mở rộng ngoài Protocol
        `ASRProvider`/`Recognizer` (ZipFormer, Gemini Live, ElevenLabs Realtime).
        Raise rõ ràng nếu provider đang cấu hình không có `stream()`, thay vì lỗi
        `AttributeError` mơ hồ ở nơi gọi."""
        provider = self._gateway.provider
        stream = getattr(provider, "stream", None)
        if stream is None:
            raise RuntimeError(
                f"ASR provider {self._gateway.provider_name!r} không hỗ trợ streaming"
            )
        return stream(frames, **kwargs)
