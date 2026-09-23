from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env dùng chung với speech / callbot.engine nên bỏ qua key lạ
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Mock phục vụ nghiệp vụ dưới tiền tố /v1; /_harness/* bot không được gọi (§4.2.4)
    clinic_mock_base_url: str = "https://clinic-mock.vmec-callbot.tech/v1"
    clinic_mock_api_key: str = ""

    # mock: gọi mock đã deploy qua HTTP. sim: clinic_mock_sim trong bộ nhớ — chỉ demo local,
    # compose prod ghi cứng mock. Xem clinic_backend.py.
    clinic_backend: Literal["mock", "sim"] = "mock"
    # Chỉ dùng khi clinic_backend=sim: bộ dữ liệu seed và scenario (tên cách nhau dấu phẩy)
    clinic_sim_dataset: Literal["listing3", "mentor_mock"] = "listing3"
    clinic_sim_scenario: str = ""

    # Nút "Reset clinic mock" và dropdown dữ liệu trên trang demo: route demo gọi /_harness/* thay
    # người test (engine không dùng). Đặt DEMO_CLINIC_ADMIN_ENABLED=false trước khung giờ chấm (§4.2.4).
    demo_clinic_admin_enabled: bool = True


settings = Settings()
