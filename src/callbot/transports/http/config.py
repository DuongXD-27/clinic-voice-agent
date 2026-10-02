from typing import Literal

from pydantic import Field, model_validator

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

    # Mount /v1/stt/* (stt_eval.py) cho PM thử chất lượng STT trên file WAV. Chỉ đặt qua env;
    # mặc định tắt vì route tải URL tùy ý và tốn CPU ASR dùng chung với cuộc gọi thật.
    stt_eval_enabled: bool = False
    # /v1/stt/turn: lượt chỉ có tiếng phòng (Silero không thấy giọng và cả file dưới −55 dBFS)
    # trả rỗng thay vì đưa vào ASR — trước đó gain +20 dB làm model bịa chữ. Số đo trên bộ PM:
    # docs/evidence/pm-preprocess-2026-10-02.md. Tắt bằng STT_EVAL_SILENCE_GATE=false.
    stt_eval_silence_gate: bool = True

    # Secret: bearer key cho /v1/calls, /v1/stt và /demo-api (auth.py), dạng sk_..., nhiều key
    # cách nhau dấu phẩy. Để trống = tắt auth.
    bot_api_keys: str = ""

    # Bản build UI phục vụ tại /ui (ui.py); rỗng = không mount
    ui_dist_dir: str

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
        if self.stt_eval_enabled and not self.api_keys():
            raise ValueError("STT_EVAL_ENABLED=true requires BOT_API_KEYS")
        return self


class ObservabilityApiSettings(YamlSettings):
    """Explicitly opt-in configuration for the internal read-only API."""

    model_config = yaml_config("http.yaml", "observability", populate_by_name=True)

    enabled: bool = Field(validation_alias="OBSERVABILITY_API_ENABLED")
    trace_dir: str = Field(validation_alias="OBSERVABILITY_TRACE_DIR")
    # Deployment-specific fallback shared with the trace writer; only from env.
    fallback_trace_dir: str = Field(default="", validation_alias="TRACE_JSONL_DIR")


settings = Settings()
