"""Single entry point for configured TTS calls; no implicit retries or failover."""

from typing import Optional

from inference.common.errors import UnsupportedProviderError
from inference.tts.base import ProviderName, TTSProvider, TTSResult
from inference.tts.config import OpenAITTSConfig, TTSConfig


class TTSGateway:
    def __init__(self, provider: TTSProvider, *, provider_name: ProviderName) -> None:
        self._provider = provider
        self.provider_name = provider_name

    @property
    def model(self) -> str:
        return self._provider.model

    def synthesize(self, text: str) -> Optional[TTSResult]:
        text = text.strip()
        if not text:
            return None
        return self._provider.synthesize(text)


def _provider_types() -> dict[str, tuple[type[TTSConfig], type]]:
    from inference.tts.providers.openai import OpenAITTS

    return {"openai": (OpenAITTSConfig, OpenAITTS)}


def create_tts_gateway(
    provider_name: ProviderName, *, config: TTSConfig | None = None
) -> TTSGateway:
    registry = _provider_types()
    if provider_name not in registry:
        raise UnsupportedProviderError("TTS", provider_name)
    config_type, provider_type = registry[provider_name]
    if config is not None and not isinstance(config, config_type):
        raise ValueError("Configuration does not match the selected provider")
    provider = provider_type(config if config is not None else config_type())
    return TTSGateway(provider, provider_name=provider_name)
