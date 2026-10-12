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
    # Provider đọc câu, gọi trước. openai: Structured Outputs (semantic_openai_model). jev: TypeSafe
    # System One, cấu hình ở llm.yaml mục typesafe; semantic_openai_* không áp dụng.
    semantic_provider: Literal["openai", "jev"]
    # Provider dự phòng, CHỈ gọi khi provider chính lỗi dịch vụ (timeout, mạng, HTTP, trả lời hỏng),
    # trong phần còn lại của trần lượt. none (hoặc trùng provider chính) = không dự phòng; đặt none để
    # đo riêng một provider. Thiếu khóa provider chính thì chỉ chạy dự phòng.
    semantic_backup_provider: Literal["none", "openai", "jev"]
    # Chỉ gọi dự phòng khi lượt còn ít nhất chừng này giây: ít hơn thì không kịp trần, chỉ tốn tiền.
    semantic_backup_min_remaining_s: float
    # Jev: nhãn có confidence thấp hơn mức này bị bỏ (đồng ý / từ chối -> AMBIGUOUS). Lâm sàng không gate.
    semantic_jev_min_confidence: float
    # Jev: xác suất "có" tối thiểu của các Noul ở câu đọc lịch / "đổi hay hủy"
    semantic_jev_min_noul: float
    semantic_openai_model: str
    # Deadline tổng từ lúc gửi model request tới khi nhận đủ response; httpx vẫn giới hạn từng pha,
    # connect riêng 1 giây. Một request, không retry model. Áp cho provider LLM (openai); Jev có
    # `semantic_jev_timeout_s` riêng.
    semantic_fallback_timeout_s: float
    # Jev: deadline tổng của một request System One. Thấp hơn trần lượt (`MODEL_TIMEOUT_S`, 4 s) để Jev
    # treo vẫn còn `semantic_backup_min_remaining_s` cho dự phòng (12/10/2026, QC qc-cn-08).
    semantic_jev_timeout_s: float
    semantic_openai_max_tokens: int
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
