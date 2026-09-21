"""Automatic speech recognition contracts, factories, and providers."""

from typing import Protocol

from inference.asr.base import ASRProvider
from inference.common.errors import UnsupportedProviderError


class ASRSettings(Protocol):
    asr_provider: str
    gemini_api_key: str
    gemini_asr_model: str
    phowhisper_model: str


def create_asr(settings: ASRSettings) -> ASRProvider:
    if settings.asr_provider == "gemini":
        from inference.asr.providers.gemini import GeminiASR

        return GeminiASR(api_key=settings.gemini_api_key, model=settings.gemini_asr_model)
    if settings.asr_provider == "phowhisper":
        from inference.asr.providers.phowhisper import PhoWhisperASR

        return PhoWhisperASR(model=settings.phowhisper_model)
    raise UnsupportedProviderError("ASR", settings.asr_provider)


__all__ = ["ASRProvider", "ASRSettings", "create_asr"]
