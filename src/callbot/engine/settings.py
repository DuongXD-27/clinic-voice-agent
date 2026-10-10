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
    # openai: Structured Outputs (semantic_fallback_model). jev: TypeSafe System One, cấu hình ở
    # llm.yaml mục typesafe; semantic_fallback_model / max_tokens không áp dụng.
    semantic_fallback_provider: Literal["openai", "jev"]
    # Jev: nhãn có confidence thấp hơn mức này bị bỏ (đồng ý / từ chối -> AMBIGUOUS). Lâm sàng không gate.
    semantic_jev_min_confidence: float
    # Jev: xác suất "có" tối thiểu của các Noul ở câu đọc lịch / "đổi hay hủy"
    semantic_jev_min_noul: float
    semantic_fallback_model: str
    # Deadline tổng từ lúc gửi model request tới khi nhận đủ response; httpx vẫn giới hạn từng pha,
    # connect riêng 1 giây. Một request, không retry model.
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
