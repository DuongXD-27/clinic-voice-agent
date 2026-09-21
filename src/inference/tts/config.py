"""Provider configuration; instantiate only the selected provider's settings."""

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
