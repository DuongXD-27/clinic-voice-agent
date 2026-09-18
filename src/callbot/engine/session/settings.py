"""Redis session configuration."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://:callbot@localhost:6379/0"
    redis_key_prefix: str = "callbot"
    session_idle_ttl_s: int = Field(default=1800, gt=0, le=7200)
    session_max_age_s: int = Field(default=7200, gt=0, le=86400)
    session_tombstone_ttl_s: int = Field(default=86400, gt=0, le=604800)
    session_max_bytes: int = Field(default=262_144, ge=16384, le=1048576)
    session_lock_lease_s: float = Field(default=60.0, ge=15.0, le=300.0)

    @model_validator(mode="after")
    def validate_retention(self) -> "SessionSettings":
        if self.session_idle_ttl_s > self.session_max_age_s:
            raise ValueError("SESSION_IDLE_TTL_S must not exceed SESSION_MAX_AGE_S")
        return self
