"""ASR gateway: nhận PCM đúng tần số model, trả text — không xử lý audio."""

from inference.asr.base import ASRProvider, ASRResult, ProviderName
from inference.asr.gateway import ASRGateway, create_asr_gateway

__all__ = ["ASRGateway", "ASRProvider", "ASRResult", "ProviderName", "create_asr_gateway"]
