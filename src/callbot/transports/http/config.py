from typing import Literal

from pydantic import model_validator

from appconfig import YamlSettings, yaml_config


class Settings(YamlSettings):
    """Giá trị mặc định: config/http.yaml; URL clinic và key chỉ qua env."""

    model_config = yaml_config("http.yaml")

    # Mock phục vụ nghiệp vụ dưới tiền tố /v1; /_harness/* bot không được gọi (§4.2.4)
    clinic_mock_base_url: str = ""
    # Secret: chỉ từ env, rỗng = chưa cấu hình
    clinic_mock_api_key: str = ""

    # mock: gọi mock đã deploy qua HTTP. sim: clinic_mock_sim trong bộ nhớ — chỉ demo local,
    # compose prod ghi cứng mock. Xem clinic_backend.py.
    clinic_backend: Literal["mock", "sim"]
    # Chỉ dùng khi clinic_backend=sim: bộ dữ liệu seed và scenario (tên cách nhau dấu phẩy)
    clinic_sim_dataset: Literal["listing3", "mentor_mock"]
    clinic_sim_scenario: str

    # Nút "Reset clinic mock" và dropdown dữ liệu trên trang demo: route demo gọi /_harness/* thay
    # người test (engine không dùng). Chỉ đặt qua env; mặc định tắt.
    demo_clinic_admin_enabled: bool = False

    # Secret: bearer key cho /v1/calls và /demo-api (auth.py), dạng sk_..., nhiều key cách nhau
    # dấu phẩy. Để trống = tắt auth.
    bot_api_keys: str = ""

    def api_keys(self) -> list[str]:
        return [key.strip() for key in self.bot_api_keys.split(",") if key.strip()]

    def require_clinic_mock_base_url(self) -> str:
        url = self.clinic_mock_base_url.strip()
        if not url:
            raise ValueError("CLINIC_MOCK_BASE_URL is required when using clinic mock")
        return url

    @model_validator(mode="after")
    def validate_demo_clinic_admin(self) -> "Settings":
        if self.demo_clinic_admin_enabled and not self.api_keys():
            raise ValueError("DEMO_CLINIC_ADMIN_ENABLED=true requires BOT_API_KEYS")
        if self.demo_clinic_admin_enabled and self.clinic_backend == "mock":
            self.require_clinic_mock_base_url()
        return self


settings = Settings()
