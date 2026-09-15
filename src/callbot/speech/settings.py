from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from callbot.speech.types import NARROWBAND_RATE, SampleRate


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Tần số chuẩn của pipeline. Mặc định băng hẹp 8 kHz như đường dây điện thoại;
    # đặt 16000 chỉ để so sánh WER, không dùng cho số liệu báo cáo.
    sample_rate: SampleRate = NARROWBAND_RATE

    asr_provider: Literal["gemini", "phowhisper"] = "gemini"
    tts_provider: Literal["none"] = "none"
    gemini_api_key: str = ""
    gemini_asr_model: str = "gemini-2.5-flash"
    phowhisper_model: str = "vinai/PhoWhisper-large"

    vad_rms_threshold: float = 500.0
    vad_end_silence_ms: int = 600

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str = "http://localhost:8000"
    audio_dir: str = "temp/audio"
