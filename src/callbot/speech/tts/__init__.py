from callbot.speech.settings import SpeechSettings
from callbot.speech.tts.base import NullTTS, TTSProvider
from callbot.speech.tts.storage import AudioArtifactStore


def create_tts(settings: SpeechSettings) -> TTSProvider:
    if settings.tts_provider == "none":
        return NullTTS()
    if settings.tts_provider == "openai":
        from callbot.speech.tts.openai import OpenAITTS

        return OpenAITTS(
            api_key=settings.openai_api_key,
            model=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
        )
    raise ValueError(f"TTS provider không hỗ trợ: {settings.tts_provider}")


__all__ = ["AudioArtifactStore", "NullTTS", "TTSProvider", "create_tts"]
