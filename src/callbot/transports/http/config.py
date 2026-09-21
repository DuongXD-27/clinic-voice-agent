from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env dùng chung với speech / callbot.engine nên bỏ qua key lạ
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Mock phục vụ nghiệp vụ dưới tiền tố /v1; /_harness/* bot không được gọi (§4.2.4)
    clinic_mock_base_url: str = "https://clinic-mock.vmec-callbot.tech/v1"
    clinic_mock_api_key: str = ""


settings = Settings()
