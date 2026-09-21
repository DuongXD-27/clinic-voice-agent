"""Provider configuration; instantiate only the selected provider's settings."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Asset ZipFormer đi kèm repo (bị .gitignore, tải tay theo docs/reference/zipformer-model-setup.md).
_ZIPFORMER_ASSETS = Path(__file__).parent / "providers" / "assets" / "zipformer"


class ASRConfig(BaseSettings):
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


class GeminiASRConfig(ASRConfig):
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_ASR_MODEL")


class PhoWhisperConfig(ASRConfig):
    model: str = Field(default="vinai/PhoWhisper-large", validation_alias="PHOWHISPER_MODEL")


class ZipFormerConfig(ASRConfig):
    model: str = "csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20"
    encoder_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "encoder-epoch-12-avg-8.int8.onnx"),
        validation_alias="ZIPFORMER_ENCODER_PATH",
    )
    decoder_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "decoder-epoch-12-avg-8.onnx"),
        validation_alias="ZIPFORMER_DECODER_PATH",
    )
    joiner_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "joiner-epoch-12-avg-8.int8.onnx"),
        validation_alias="ZIPFORMER_JOINER_PATH",
    )
    tokens_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "tokens.txt"), validation_alias="ZIPFORMER_TOKENS_PATH"
    )
    num_threads: int = Field(default=2, gt=0)
