from typing import Literal

from appconfig import YamlSettings, yaml_config


class EngineSettings(YamlSettings):
    """Giá trị mặc định: config/engine.yaml."""

    model_config = yaml_config("engine.yaml")

    name_fallback_provider: Literal["none", "openai", "gemini", "groq", "openrouter"]

    # Tầng ngữ nghĩa (T-05 §8). Mặc định BẬT theo quyết định owner 22-09-2026, dù bước 7 (đánh giá
    # model thật) chưa chạy. Thiếu OPENAI_API_KEY thì factory tự về chỉ-luật, không chặn khởi động.
    # Tắt: SEMANTIC_FALLBACK_ENABLED=false. Cấu hình riêng, không dùng chung `NAME_FALLBACK_*`.
    semantic_fallback_enabled: bool
    semantic_fallback_model: str
    # httpx.Timeout theo PHA (connect riêng 1 giây; đọc / ghi / chờ pool mỗi pha tối đa 3 giây), không
    # phải trần tổng của request. Một request, không retry model.
    semantic_fallback_timeout_s: float
    semantic_fallback_max_tokens: int
    # Câu dài hơn mức này thì hỏi ngắn lại, không âm thầm cắt (cắt có thể mất chính lời phủ định).
    semantic_fallback_max_input_chars: int
    # Cho model đề xuất xác nhận hủy, luật kiểm chứng (evidence T-05, đợt 3).
    # Mặc định TẮT: tắt thì prompt (semantic_v5), route và merge y hệt trước đây. Chỉ bật khi đạt
    # điều kiện §7 của plan (test đối kháng, 5 repeat model thật không ghi hủy sai, snapshot).
    cancel_semantic_confirm_enabled: bool

    clinic_id: str

    # §1.1.5: chuyển máy sau 2 lần liên tiếp không hiểu
    max_failed_understandings: int
    # §1.1.7: kết thúc UNREACHABLE sau 3 lượt im lặng liên tiếp
    max_silent_turns: int
