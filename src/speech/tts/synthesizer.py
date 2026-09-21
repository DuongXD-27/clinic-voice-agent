"""Nối TTS gateway vào miền audio của `speech`: trả `AudioSegment`."""

from typing import Optional, Protocol

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

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        result = self._gateway.synthesize(text)
        if result is None:
            return None
        return AudioSegment(pcm=result.pcm, sample_rate=result.sample_rate)
