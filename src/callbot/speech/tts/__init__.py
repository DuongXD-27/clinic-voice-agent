from callbot.speech.settings import SpeechSettings
from callbot.speech.tts.base import NullTTS, TTSProvider
from callbot.speech.tts.storage import AudioArtifactStore


def create_tts(settings: SpeechSettings) -> TTSProvider:
    if settings.tts_provider == "none":
        return NullTTS()
    raise ValueError(f"TTS provider không hỗ trợ: {settings.tts_provider}")


__all__ = ["AudioArtifactStore", "NullTTS", "TTSProvider", "create_tts"]
