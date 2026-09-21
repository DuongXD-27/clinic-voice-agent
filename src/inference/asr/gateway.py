"""Single entry point for configured ASR calls; no implicit retries or failover."""

from inference.asr.base import ASRProvider, ASRResult, ProviderName
from inference.asr.config import ASRConfig, GeminiASRConfig, PhoWhisperConfig, ZipFormerConfig
from inference.common.errors import UnsupportedProviderError


class ASRGateway:
    def __init__(self, provider: ASRProvider, *, provider_name: ProviderName) -> None:
        self._provider = provider
        self.provider_name = provider_name

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def input_sample_rate(self) -> int:
        return self._provider.input_sample_rate

    def transcribe(self, pcm: bytes, sample_rate: int) -> ASRResult:
        if sample_rate != self.input_sample_rate:
            raise ValueError(
                f"{self.provider_name} expects {self.input_sample_rate} Hz audio, got {sample_rate}"
            )
        if not pcm:
            return ASRResult(text="")
        return self._provider.transcribe(pcm)


def _provider_types() -> dict[str, tuple[type[ASRConfig], type]]:
    # Import trễ: mỗi provider kéo theo SDK nặng (sherpa-onnx, transformers, google-genai).
    from inference.asr.providers.gemini import GeminiASR
    from inference.asr.providers.phowhisper import PhoWhisperASR
    from inference.asr.providers.zipformer import ZipFormerASR

    return {
        "gemini": (GeminiASRConfig, GeminiASR),
        "phowhisper": (PhoWhisperConfig, PhoWhisperASR),
        "zipformer": (ZipFormerConfig, ZipFormerASR),
    }


def create_asr_gateway(
    provider_name: ProviderName, *, config: ASRConfig | None = None
) -> ASRGateway:
    registry = _provider_types()
    if provider_name not in registry:
        raise UnsupportedProviderError("ASR", provider_name)
    config_type, provider_type = registry[provider_name]
    if config is not None and not isinstance(config, config_type):
        raise ValueError("Configuration does not match the selected provider")
    provider = provider_type(config if config is not None else config_type())
    return ASRGateway(provider, provider_name=provider_name)
