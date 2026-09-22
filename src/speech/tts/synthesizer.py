"""Nối TTS gateway vào miền audio của `speech`: trả `AudioSegment`."""

from typing import AsyncIterator, Optional, Protocol

from inference.tts import TTSGateway
from speech.types import AudioSegment


class Synthesizer(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


class SpeechSynthesizer:
    def __init__(self, gateway: TTSGateway) -> None:
        self._gateway = gateway

    @property
    def name(self) -> str:
        return self._gateway.provider_name

    @property
    def model(self) -> str:
        return self._gateway.model

    @property
    def stream_sample_rate(self) -> int:
        return getattr(self._gateway.provider, "stream_sample_rate", 24_000)

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        result = self._gateway.synthesize(text)
        if result is None:
            return None
        return AudioSegment(pcm=result.pcm, sample_rate=result.sample_rate)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Ủy quyền xuống `synthesize_stream()` của provider gốc — method mở rộng
        ngoài Protocol `TTSProvider`/`Synthesizer`. Raise
        rõ ràng nếu provider đang cấu hình không có `synthesize_stream()`."""
        provider = self._gateway.provider
        stream = getattr(provider, "synthesize_stream", None)
        if stream is None:
            raise RuntimeError(
                f"TTS provider {self._gateway.provider_name!r} không hỗ trợ streaming"
            )
        async for chunk in stream(text):
            yield chunk

    async def cancel(self) -> None:
        """No-op nếu provider không hỗ trợ cancel (không phải mọi provider có streaming
        cần huỷ giữa chừng)."""
        cancel = getattr(self._gateway.provider, "cancel", None)
        if cancel is not None:
            await cancel()
