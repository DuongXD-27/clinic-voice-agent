"""Single entry point for configured ASR calls; no implicit retries or failover."""

from inference.asr.base import ASRProvider, ASRResult, ProviderName
from inference.asr.config import (
    ASRConfig,
    ElevenLabsRealtimeConfig,
    GeminiASRConfig,
    GeminiLiveASRConfig,
    PhoWhisperConfig,
    ZipFormerConfig,
)
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

    @property
    def provider(self) -> ASRProvider:
        """Escape hatch cho caller cần method mở rộng ngoài Protocol (vd. `stream()`
        của ZipFormerASR cho LiveKit) — KHÔNG dùng cho `transcribe()` thường, chỉ khi
        caller đã biết trước provider nào đang chạy và kiểm tra bằng `hasattr`/`getattr`.
        Không phá lazy-loading: registry vẫn resolve qua `create_asr_gateway()` như cũ,
        property này chỉ expose instance đã tạo."""
        return self._provider

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
    from inference.asr.providers.elevenlabs_realtime import ElevenLabsRealtimeASR
    from inference.asr.providers.gemini import GeminiASR
    from inference.asr.providers.gemini_live import GeminiLiveASR
    from inference.asr.providers.phowhisper import PhoWhisperASR
    from inference.asr.providers.zipformer import ZipFormerASR

    return {
        "gemini": (GeminiASRConfig, GeminiASR),
        "gemini_live": (GeminiLiveASRConfig, GeminiLiveASR),
        "phowhisper": (PhoWhisperConfig, PhoWhisperASR),
        "zipformer": (ZipFormerConfig, ZipFormerASR),
        "elevenlabs_realtime": (ElevenLabsRealtimeConfig, ElevenLabsRealtimeASR),
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
