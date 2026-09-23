from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env dùng chung với speech / callbot.engine nên bỏ qua key lạ
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Mock phục vụ nghiệp vụ dưới tiền tố /v1; /_harness/* bot không được gọi (§4.2.4)
    clinic_mock_base_url: str = "https://clinic-mock.vmec-callbot.tech/v1"
    clinic_mock_api_key: str = ""


class ObservabilityApiSettings(BaseSettings):
    """Explicitly opt-in configuration for the internal read-only API."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    enabled: bool = Field(default=False, validation_alias="OBSERVABILITY_API_ENABLED")
    trace_dir: str = Field(default="", validation_alias="OBSERVABILITY_TRACE_DIR")
    fallback_trace_dir: str = Field(default="", validation_alias="TRACE_JSONL_DIR")


settings = Settings()
