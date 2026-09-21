from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from callbot.speech.types import NARROWBAND_RATE, SampleRate


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Tần số chuẩn của pipeline. Mặc định băng hẹp 8 kHz như đường dây điện thoại;
    # đặt 16000 chỉ để so sánh WER, không dùng cho số liệu báo cáo.
    sample_rate: SampleRate = NARROWBAND_RATE

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _coerce_sample_rate(cls, value: Any) -> Any:
        # Env luôn là chuỗi ("8000") mà Literal[int] không tự ép kiểu -> SpeechSettings() lỗi khi .env có SAMPLE_RATE
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
        return value

    asr_provider: Literal["gemini", "phowhisper"] = "gemini"
    tts_provider: Literal["none", "elevenlabs"] = "none"
    # ElevenLabs qua WebSocket stream-input (speech/tts/elevenlabs.py); voice_id lấy từ tài khoản
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_timeout_s: float = 4.0
    # pcm_8000 khớp băng hẹp, không phải resample; tuần 5 điện thoại có thể dùng ulaw_8000
    elevenlabs_output_format: str = "pcm_8000"
    # Ép model đọc tiếng Việt kể cả câu ngắn dễ đoán nhầm ngôn ngữ; rỗng = để model tự đoán
    elevenlabs_language_code: str = "vi"
    gemini_api_key: str = ""
    gemini_asr_model: str = "gemini-2.5-flash"
    phowhisper_model: str = "vinai/PhoWhisper-large"

    vad_rms_threshold: float = 500.0
    vad_end_silence_ms: int = 600

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str = "http://localhost:8000"
    audio_dir: str = "temp/audio"
