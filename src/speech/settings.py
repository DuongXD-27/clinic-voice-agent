from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inference.asr import ProviderName as ASRProviderName
from inference.tts import ProviderName as TTSProviderName
from speech.types import NARROWBAND_RATE, SampleRate


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Tần số chuẩn của pipeline. Mặc định băng hẹp 8 kHz như đường dây điện thoại;
    # đặt 16000 chỉ để so sánh WER, không dùng cho số liệu báo cáo.
    sample_rate: SampleRate = NARROWBAND_RATE

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _coerce_sample_rate(cls, value: object) -> object:
        # pydantic không tự coerce string "8000" từ .env thành Literal[int] — ép tay.
        return int(value) if isinstance(value, str) else value

    # Chỉ chọn provider; model/API key của từng provider do inference.asr.config /
    # inference.tts.config đọc từ env (GEMINI_ASR_MODEL, ZIPFORMER_*_PATH, OPENAI_TTS_MODEL...).
    asr_provider: ASRProviderName = "gemini"
    tts_provider: TTSProviderName = "openai"

    vad_rms_threshold: float = 500.0
    vad_end_silence_ms: int = 600

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str = "http://localhost:8000"
    audio_dir: str = "temp/audio"
