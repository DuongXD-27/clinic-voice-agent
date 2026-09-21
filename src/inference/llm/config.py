"""Provider configuration; instantiate only the selected provider's settings."""

from typing import ClassVar, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    endpoint: ClassVar[str]
    key_env: ClassVar[str]
    connect_timeout_s: ClassVar[float] = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    api_key: SecretStr
    model: str
    timeout_s: float = Field(
        default=3.0, gt=0, allow_inf_nan=False, validation_alias="NAME_FALLBACK_TIMEOUT_S"
    )
    max_completion_tokens: int = Field(
        default=200, gt=0, validation_alias="NAME_FALLBACK_MAX_TOKENS"
    )

    @field_validator("model", "max_completion_tokens", mode="before")
    @classmethod
    def empty_uses_provider_default(cls, value, info):
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].default
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_api_key(self) -> Self:
        if not self.api_key.get_secret_value().strip():
            raise ValueError(f"Selected provider requires {self.key_env}")
        return self


class OpenAIConfig(ProviderConfig):
    endpoint = "https://api.openai.com/v1/chat/completions"
    key_env = "OPENAI_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-4o-mini", min_length=1, validation_alias="NAME_FALLBACK_MODEL")


class GeminiConfig(ProviderConfig):
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models"
    key_env = "GEMINI_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    model: str = Field(
        default="gemini-2.5-flash", min_length=1, validation_alias="NAME_FALLBACK_MODEL"
    )


class GroqConfig(ProviderConfig):
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    key_env = "GROQ_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")
    model: str = Field(
        default="openai/gpt-oss-20b", min_length=1, validation_alias="NAME_FALLBACK_MODEL"
    )
    # Reasoning models share the budget between reasoning and final JSON.
    max_completion_tokens: int = Field(
        default=1024, gt=0, validation_alias="NAME_FALLBACK_MAX_TOKENS"
    )


class OpenRouterConfig(ProviderConfig):
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    key_env = "OPENROUTER_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENROUTER_API_KEY")
    model: str = Field(
        default="openai/gpt-4o-mini", min_length=1, validation_alias="NAME_FALLBACK_MODEL"
    )
