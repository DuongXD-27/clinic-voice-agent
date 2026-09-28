"""Redis session configuration. Giá trị mặc định: config/session.yaml."""

from pydantic import Field, model_validator

from appconfig import YamlSettings, yaml_config


class SessionSettings(YamlSettings):
    model_config = yaml_config("session.yaml")

    redis_url: str
    # Giá trị dự phòng để bản deploy cũ chưa có REDIS_KEY_PREFIX vẫn đọc được session đang chạy.
    redis_key_prefix: str = "callbot"
    session_idle_ttl_s: int = Field(gt=0, le=7200)
    session_max_age_s: int = Field(gt=0, le=86400)
    session_tombstone_ttl_s: int = Field(gt=0, le=604800)
    session_max_bytes: int = Field(ge=16384, le=1048576)
    session_lock_lease_s: float = Field(ge=15.0, le=300.0)

    @model_validator(mode="after")
    def validate_retention(self) -> "SessionSettings":
        if self.session_idle_ttl_s > self.session_max_age_s:
            raise ValueError("SESSION_IDLE_TTL_S must not exceed SESSION_MAX_AGE_S")
        return self
