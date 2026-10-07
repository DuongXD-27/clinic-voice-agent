"""Provider configuration; instantiate only the selected provider's settings.

Giá trị mặc định ở config/llm.yaml (mỗi provider một section); API key chỉ đặt qua env.
"""

from typing import ClassVar, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from appconfig import YamlSettings, yaml_config


class ProviderConfig(YamlSettings):
    key_env: ClassVar[str]

    model_config = SettingsConfigDict(populate_by_name=True, hide_input_in_errors=True)

    api_key: SecretStr
    # Field không alias đọc env theo env_prefix của lớp con: OPENAI_ENDPOINT, GROQ_CONNECT_TIMEOUT_S...
    endpoint: str = Field(min_length=1)
    model: str = Field(min_length=1, validation_alias="NAME_FALLBACK_MODEL")
    timeout_s: float = Field(gt=0, allow_inf_nan=False, validation_alias="NAME_FALLBACK_TIMEOUT_S")
    connect_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    max_completion_tokens: int = Field(gt=0, validation_alias="NAME_FALLBACK_MAX_TOKENS")

    @field_validator("model", mode="before")
    @classmethod
    def strip_model(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_api_key(self) -> Self:
        if not self.api_key.get_secret_value().strip():
            raise ValueError(f"Selected provider requires {self.key_env}")
        return self


class OpenAIConfig(ProviderConfig):
    model_config = yaml_config("llm.yaml", "openai", env_prefix="OPENAI_")
    key_env = "OPENAI_API_KEY"
    service_tier: Literal["auto", "default", "fast", "priority", "flex"]
    # Secret: chỉ từ env, rỗng = chưa cấu hình (require_api_key báo lỗi)
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")


class GeminiConfig(ProviderConfig):
    model_config = yaml_config("llm.yaml", "gemini", env_prefix="GEMINI_")
    key_env = "GEMINI_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")


class GroqConfig(ProviderConfig):
    model_config = yaml_config("llm.yaml", "groq", env_prefix="GROQ_")
    key_env = "GROQ_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")


class OpenRouterConfig(ProviderConfig):
    model_config = yaml_config("llm.yaml", "openrouter", env_prefix="OPENROUTER_")
    key_env = "OPENROUTER_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENROUTER_API_KEY")
