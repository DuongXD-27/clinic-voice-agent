"""Provider configuration; instantiate only the selected provider's settings.

Giá trị mặc định ở config/llm.yaml (mỗi provider một section); API key chỉ đặt qua env.
"""

from pathlib import Path
from typing import Any, ClassVar, Literal, Self

import yaml
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


def yaml_default(config_type: type[ProviderConfig], field: str) -> Any:
    """Giá trị trong config/llm.yaml của provider, không qua env.

    Tầng ngữ nghĩa dùng hàm này thay vì để `ProviderConfig` tự đọc: field không truyền sẽ lấy
    `NAME_FALLBACK_*` (alias của slot filling họ tên), làm hai tầng dính cấu hình nhau.
    """
    settings = config_type.model_config
    data = yaml.safe_load(Path(settings["yaml_file"]).read_text(encoding="utf-8"))
    return data[settings["yaml_config_section"]][field]


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


class DeepSeekConfig(ProviderConfig):
    model_config = yaml_config("llm.yaml", "deepseek", env_prefix="DEEPSEEK_")
    key_env = "DEEPSEEK_API_KEY"
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="DEEPSEEK_API_KEY")


class TypeSafeConfig(YamlSettings):
    """TypeSafe System One (Jev). Không kế thừa `ProviderConfig`: không có max tokens, không đọc
    `NAME_FALLBACK_*` — Jev chỉ dùng cho tầng ngữ nghĩa."""

    model_config = yaml_config(
        "llm.yaml", "typesafe", env_prefix="TYPESAFE_", hide_input_in_errors=True
    )
    key_env: ClassVar[str] = "TYPESAFE_API_KEY"

    # Secret: chỉ từ env, rỗng = chưa cấu hình (require_api_key báo lỗi)
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="TYPESAFE_API_KEY")
    endpoint: str = Field(min_length=1)
    model: str = Field(min_length=1)
    timeout_s: float = Field(gt=0, allow_inf_nan=False)
    connect_timeout_s: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_api_key(self) -> Self:
        if not self.api_key.get_secret_value().strip():
            raise ValueError(f"TypeSafe requires {self.key_env}")
        return self
