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
    if settings.tts_provider == "vbee":
        if not settings.vbee_access_token:
            raise ValueError("TTS_PROVIDER=vbee cần VBEE_ACCESS_TOKEN")
        if not settings.vbee_app_id:
            raise ValueError("TTS_PROVIDER=vbee cần VBEE_APP_ID")
        if not settings.vbee_voice_code:
            raise ValueError("TTS_PROVIDER=vbee cần VBEE_VOICE_CODE")
        from callbot.speech.tts.vbee import VbeeTTS

        return VbeeTTS(
            settings.vbee_access_token,
            settings.vbee_app_id,
            settings.vbee_voice_code,
            sample_rate=settings.vbee_sample_rate,
            speed=settings.vbee_speed,
            timeout_s=settings.vbee_timeout_s,
            base_url=settings.vbee_base_url,
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
