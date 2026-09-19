from typing import Literal

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
    def _coerce_sample_rate(cls, value: object) -> object:
        # pydantic không tự coerce string "8000" từ .env thành Literal[int] — ép tay.
        return int(value) if isinstance(value, str) else value

    asr_provider: Literal["gemini", "phowhisper", "zipformer"] = "gemini"
    tts_provider: Literal["none", "openai"] = "none"
    gemini_api_key: str = ""
    gemini_asr_model: str = "gemini-2.5-flash"
    phowhisper_model: str = "vinai/PhoWhisper-large"

    # OpenAI TTS dùng cho mode="audio" trên đường HTTP chấm điểm (xem tts/openai.py).
    openai_api_key: str = ""
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"

    # ZipFormer 68M self-host qua sherpa-onnx (batch, xem asr/zipformer.py). Mặc định
    # trỏ vào asset đi kèm repo (asr/assets/zipformer/); đổi qua .env nếu dùng model khác.
    zipformer_encoder_path: str = ""
    zipformer_decoder_path: str = ""
    zipformer_joiner_path: str = ""
    zipformer_tokens_path: str = ""

    vad_rms_threshold: float = 500.0
    vad_end_silence_ms: int = 600

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str = "http://localhost:8000"
    audio_dir: str = "temp/audio"
