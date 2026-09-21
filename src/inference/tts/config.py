"""Provider configuration; instantiate only the selected provider's settings."""

from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TTSConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def empty_uses_provider_default(cls, value, info):
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].get_default()
        return value.strip() if isinstance(value, str) else value


class OpenAITTSConfig(TTSConfig):
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    model: str = Field(default="tts-1", validation_alias="OPENAI_TTS_MODEL")
    voice: str = Field(default="alloy", validation_alias="OPENAI_TTS_VOICE")


class ElevenLabsTTSConfig(TTSConfig):
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ELEVENLABS_API_KEY")
    voice_id: str = Field(default="", validation_alias="ELEVENLABS_VOICE_ID")
    model: str = Field(default="eleven_flash_v2_5", validation_alias="ELEVENLABS_MODEL")
    timeout_s: float = Field(default=4.0, validation_alias="ELEVENLABS_TIMEOUT_S")
    # pcm_8000 khớp băng hẹp, không phải resample; tuần 5 điện thoại có thể dùng ulaw_8000
    output_format: str = Field(default="pcm_8000", validation_alias="ELEVENLABS_OUTPUT_FORMAT")
    # Ép model đọc tiếng Việt kể cả câu ngắn dễ đoán nhầm ngôn ngữ; None = để model tự đoán.
    # Env rỗng ("") bị `empty_uses_provider_default` coi là "chưa đặt" nên vẫn ra "vi", không phải
    # auto-detect — muốn auto-detect thì truyền None trực tiếp (constructor/test), không qua .env.
    language_code: Optional[str] = Field(default="vi", validation_alias="ELEVENLABS_LANGUAGE_CODE")
