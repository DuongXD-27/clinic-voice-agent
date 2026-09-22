from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    name_fallback_provider: Literal["none", "openai", "gemini", "groq", "openrouter"] = "none"

    # Tầng ngữ nghĩa (T-05 §8). Mặc định BẬT theo quyết định owner 22-09-2026, dù bước 7 (đánh giá
    # model thật) chưa chạy. Thiếu OPENAI_API_KEY thì factory tự về chỉ-luật, không chặn khởi động.
    # Tắt: SEMANTIC_FALLBACK_ENABLED=false. Cấu hình riêng, không dùng chung `NAME_FALLBACK_*`.
    semantic_fallback_enabled: bool = True
    semantic_fallback_model: str = "gpt-4o-mini"
    semantic_fallback_timeout_s: float = 2.0
    semantic_fallback_max_tokens: int = 400
    # Câu dài hơn mức này thì hỏi ngắn lại, không âm thầm cắt (cắt có thể mất chính lời phủ định).
    semantic_fallback_max_input_chars: int = 1500

    clinic_id: str = "cl_vinmec"

    # §1.1.5: chuyển máy sau 2 lần liên tiếp không hiểu
    max_failed_understandings: int = 2
    # §1.1.7: kết thúc UNREACHABLE sau 3 lượt im lặng liên tiếp
    max_silent_turns: int = 3
