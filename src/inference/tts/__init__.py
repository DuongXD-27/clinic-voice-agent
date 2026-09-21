"""Text-to-speech contracts, factories, and providers."""

from typing import Protocol

from inference.common.errors import UnsupportedProviderError
from inference.tts.base import TTSProvider
from inference.tts.providers.null import NullTTS


class TTSSettings(Protocol):
    tts_provider: str


def create_tts(settings: TTSSettings) -> TTSProvider:
    if settings.tts_provider == "none":
        return NullTTS()
    raise UnsupportedProviderError("TTS", settings.tts_provider)


__all__ = ["NullTTS", "TTSProvider", "TTSSettings", "create_tts"]
