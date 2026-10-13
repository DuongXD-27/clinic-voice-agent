from typing import Literal, Optional, Union

from appconfig import YamlSettings, yaml_config
from inference.llm.providers.base import ProviderName

# Tầng ngữ nghĩa: Jev hoặc một provider LLM bất kỳ của gateway (cấu hình ở llm.yaml)
SemanticProvider = Union[Literal["jev"], ProviderName]


class EngineSettings(YamlSettings):
    """Giá trị mặc định: config/engine.yaml."""

    model_config = yaml_config("engine.yaml")

    name_fallback_provider: Union[Literal["none"], ProviderName]

    # Tầng ngữ nghĩa (T-05 §8). Mặc định BẬT theo quyết định owner 22-09-2026, dù bước 7 (đánh giá
    # model thật) chưa chạy. Thiếu khóa provider thì factory tự về chỉ-luật, không chặn khởi động.
    # Tắt: SEMANTIC_FALLBACK_ENABLED=false. Cấu hình riêng, không dùng chung `NAME_FALLBACK_*`.
    semantic_fallback_enabled: bool
    # Provider đọc câu, gọi trước. jev: TypeSafe System One (llm.yaml mục typesafe). Provider LLM
    # (openai, deepseek, ...): structured output qua gateway, dùng semantic_llm_*; Jev không dùng chúng.
    semantic_provider: SemanticProvider
    # Provider dự phòng, CHỈ gọi khi provider chính lỗi dịch vụ (timeout, mạng, HTTP, trả lời hỏng),
    # trong phần còn lại của trần lượt. none (hoặc trùng provider chính) = không dự phòng; đặt none để
    # đo riêng một provider. Thiếu khóa provider chính thì chỉ chạy dự phòng.
    semantic_backup_provider: Union[Literal["none"], SemanticProvider]
    # Chỉ gọi dự phòng khi lượt còn ít nhất chừng này giây: ít hơn thì không kịp trần, chỉ tốn tiền.
    semantic_backup_min_remaining_s: float
    # Jev: nhãn có confidence thấp hơn mức này bị bỏ (đồng ý / từ chối -> AMBIGUOUS). Lâm sàng không gate.
    semantic_jev_min_confidence: float
    # Jev: xác suất "có" tối thiểu của các Noul ở câu đọc lịch / "đổi hay hủy"
    semantic_jev_min_noul: float
    # Model của provider LLM ở tầng ngữ nghĩa và tầng chọn khung. Trống = model của provider đó trong
    # llm.yaml (không đọc NAME_FALLBACK_MODEL), nên đổi provider không cần đổi model theo.
    semantic_llm_model: Optional[str]
    # Deadline tổng từ lúc gửi model request tới khi nhận đủ response; httpx vẫn giới hạn từng pha,
    # connect riêng 1 giây. Một request, không retry model. Áp cho provider LLM; Jev có
    # `semantic_jev_timeout_s` riêng.
    semantic_fallback_timeout_s: float
    # Jev: deadline tổng của một request System One. Thấp hơn trần lượt (`MODEL_TIMEOUT_S`, 4 s) để Jev
    # treo vẫn còn `semantic_backup_min_remaining_s` cho dự phòng (12/10/2026, QC qc-cn-08).
    semantic_jev_timeout_s: float
    semantic_llm_max_tokens: int
    # Prompt của provider LLM (một trong PROMPT_VERSIONS của inference.llm.prompt.semantic). Trống = tự
    # chọn: tắt cancel_semantic_confirm_enabled -> semantic_v5; bật -> semantic_v10_luna với GPT-6 Luna,
    # model khác semantic_v6. Đặt tường minh để model khác dùng đúng prompt của Luna.
    semantic_llm_prompt_version: Optional[str]
    # Câu dài hơn mức này thì hỏi ngắn lại, không âm thầm cắt (cắt có thể mất chính lời phủ định).
    semantic_fallback_max_input_chars: int
    # Cho model đề xuất xác nhận hủy, luật kiểm chứng (evidence T-05, đợt 3).
    # Mặc định TẮT: tắt thì prompt (semantic_v5), route và merge y hệt trước đây. Chỉ bật khi đạt
    # điều kiện §7 của plan (test đối kháng, 5 repeat model thật không ghi hủy sai, snapshot).
    cancel_semantic_confirm_enabled: bool
    # Model đọc câu khó ở 4 câu hỏi chọn khung (plan t10-slot-semantic-jev-2026-10-12.md). Mặc định TẮT:
    # tắt thì router không chạy, hành vi y hệt chỉ-luật. Jev chính (ngưỡng dùng chung semantic_jev_*),
    # provider LLM dự phòng (semantic_llm_model) khi câu không dấu hoặc Jev lỗi dịch vụ.
    slot_semantic_enabled: bool
    # Provider LLM dự phòng của route chọn khung; none = chỉ Jev
    slot_semantic_backup_provider: Union[Literal["none"], ProviderName]
    # Trần request Jev ở route chọn khung; quá thì sang provider LLM nếu lượt còn đủ giờ
    slot_semantic_jev_timeout_s: float
    # Trần request provider LLM ở route chọn khung
    slot_semantic_llm_timeout_s: float
    # Trần cả lượt của route chọn khung (gồm đường dự phòng); vẫn dưới 8 s / lượt của contract §4.1.2
    slot_semantic_budget_s: float

    clinic_id: str

    # §1.1.5: chuyển máy sau 2 lần liên tiếp không hiểu
    max_failed_understandings: int
    # §1.1.7: kết thúc UNREACHABLE sau 3 lượt im lặng liên tiếp
    max_silent_turns: int
