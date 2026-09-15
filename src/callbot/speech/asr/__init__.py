from callbot.speech.asr.base import ASRProvider
from callbot.speech.settings import SpeechSettings


def create_asr(settings: SpeechSettings) -> ASRProvider:
    if settings.asr_provider == "gemini":
        from callbot.speech.asr.gemini import GeminiASR

        return GeminiASR(api_key=settings.gemini_api_key, model=settings.gemini_asr_model)
    if settings.asr_provider == "phowhisper":
        from callbot.speech.asr.phowhisper import PhoWhisperASR

        return PhoWhisperASR(model=settings.phowhisper_model)
    raise ValueError(f"ASR provider không hỗ trợ: {settings.asr_provider}")


__all__ = ["ASRProvider", "create_asr"]
