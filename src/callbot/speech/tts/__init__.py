from callbot.speech.settings import SpeechSettings
from callbot.speech.tts.base import NullTTS, TTSProvider, TTSTiming
from callbot.speech.tts.errors import TTSError, TTSRejected, TTSUnavailable
from callbot.speech.tts.storage import AudioArtifactStore


def create_tts(settings: SpeechSettings) -> TTSProvider:
    if settings.tts_provider == "none":
        return NullTTS()
    if settings.tts_provider == "elevenlabs":
        # Fail-fast lúc khởi động: thiếu cấu hình thì không đợi tới lượt 0 mới lỗi
        if not settings.elevenlabs_api_key:
            raise ValueError("TTS_PROVIDER=elevenlabs cần ELEVENLABS_API_KEY")
        if not settings.elevenlabs_voice_id:
            raise ValueError("TTS_PROVIDER=elevenlabs cần ELEVENLABS_VOICE_ID")
        from callbot.speech.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(
            settings.elevenlabs_api_key,
            settings.elevenlabs_voice_id,
            settings.elevenlabs_model,
            timeout_s=settings.elevenlabs_timeout_s,
            output_format=settings.elevenlabs_output_format,
            language_code=settings.elevenlabs_language_code or None,
        )
    raise ValueError(f"TTS provider không hỗ trợ: {settings.tts_provider}")


__all__ = [
    "AudioArtifactStore",
    "NullTTS",
    "TTSError",
    "TTSProvider",
    "TTSRejected",
    "TTSTiming",
    "TTSUnavailable",
    "create_tts",
]
