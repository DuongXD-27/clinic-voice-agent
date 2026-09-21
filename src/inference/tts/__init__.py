"""TTS gateway: nhận text, trả PCM của provider — không xử lý audio."""

from inference.tts.base import ProviderName, TTSProvider, TTSResult
from inference.tts.gateway import TTSGateway, create_tts_gateway

__all__ = ["ProviderName", "TTSGateway", "TTSProvider", "TTSResult", "create_tts_gateway"]
