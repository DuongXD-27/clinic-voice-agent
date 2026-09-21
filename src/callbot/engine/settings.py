from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    name_fallback_provider: Literal["none", "openai", "gemini", "groq", "openrouter"] = "none"

    clinic_id: str = "cl_vinmec"

    # §1.1.5: chuyển máy sau 2 lần liên tiếp không hiểu
    max_failed_understandings: int = 2
    # §1.1.7: kết thúc UNREACHABLE sau 3 lượt im lặng liên tiếp
    max_silent_turns: int = 3
