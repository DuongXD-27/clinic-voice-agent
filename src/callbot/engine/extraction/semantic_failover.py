"""Provider chính, lỗi dịch vụ thì provider dự phòng — trong cùng MỘT ngân sách model của lượt.

Cấu hình ở `config/engine.yaml`: `semantic_provider` (chính), `semantic_backup_provider`
(dự phòng), `semantic_backup_min_remaining_s`. Mặc định Jev chính, OpenAI dự phòng.

Chỉ chuyển khi provider chính không trả lời được (timeout, lỗi mạng / HTTP, trả lời hỏng hoặc thiếu,
exception). Khi provider chính đã trả lời — kể cả đọc ra "chưa rõ" hay bị `ground_reading` loại span
— đó là kết quả của lượt: gọi thêm provider khác lúc đó là hỏi tới khi vừa ý, không phải dự phòng.

Thời gian tính từ đầu lượt (`model_budget.MODEL_TIMEOUT_S`, trần 4 s): provider chính lỗi muộn thì
không còn đủ thời gian, lượt đi đường "model không dùng được" như cũ. Hai provider đều đi qua đúng
`ground_reading` / `merge_semantic`, nên bảng quyền hợp nhất, chốt SF-05 và quy tắc model không mở khóa
ghi không đổi.
"""

import logging
from collections.abc import Callable
from time import monotonic
from typing import Any, Optional

from callbot.engine.extraction.model_budget import MODEL_TIMEOUT_S, hand_over_model
from callbot.engine.extraction.semantic import SemanticContext, SemanticOutcome

logger = logging.getLogger(__name__)

# Trạng thái adapter (`last_status`) được coi là lỗi dịch vụ. "error" = exception trong lúc gọi
# (adapter đặt trước khi gọi); "incomplete" = LLM hết token giữa chừng. "refusal" là model đã trả lời.
SERVICE_FAILURES = frozenset(
    {"timeout", "network_error", "http_error", "invalid_response", "incomplete", "error"}
)


class FailoverSemanticExtractor:
    """`SemanticExtractor`: `primary`, lỗi dịch vụ thì `secondary`. Cả hai cần thuộc tính `last_status`."""

    def __init__(
        self,
        primary: Any,
        secondary: Any,
        *,
        min_secondary_s: float,
        budget_s: float = MODEL_TIMEOUT_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not 0 <= min_secondary_s <= budget_s:
            raise ValueError("semantic_backup_min_remaining_s phải trong [0, trần lượt]")
        self.primary = primary
        self.secondary = secondary
        self._min_secondary_s = min_secondary_s
        self._budget_s = budget_s
        self._clock = clock
        # Provider đã trả kết quả của lượt gần nhất ("primary" / "secondary" / None); cho eval / trace
        self.last_provider: Optional[str] = None

    # `ModelBudget` và script eval đọc `_gateway`, `prompt_version`, `last_probabilities` của adapter:
    # trỏ về provider chính để hành vi khi nó trả lời y hệt adapter đứng một mình.
    @property
    def _gateway(self) -> Any:
        return self.primary._gateway

    @_gateway.setter
    def _gateway(self, gateway: Any) -> None:
        self.primary._gateway = gateway

    @property
    def prompt_version(self) -> str:
        return self.primary.prompt_version

    @property
    def last_probabilities(self) -> Optional[dict[str, object]]:
        return getattr(self.primary, "last_probabilities", None)

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        started = self._clock()
        self.last_provider = None
        try:
            outcome = self.primary.analyze(context)
            failed = self.primary.last_status in SERVICE_FAILURES
        except Exception:  # noqa: BLE001 — lỗi provider chính không được thành lỗi lượt
            outcome, failed = None, True
        if not failed:
            self.last_provider = "primary"
            return outcome
        remaining = self._budget_s - (self._clock() - started)
        if remaining < self._min_secondary_s:
            logger.info(
                "Semantic failover: skipped",
                extra={"semantic_failover": "skipped", "semantic_remaining_s": round(remaining, 3)},
            )
            return None
        secondary = self.secondary._gateway
        # Không log transcript — chỉ trạng thái và thời gian còn lại
        logger.info(
            "Semantic failover: %s",
            secondary.provider_name,
            extra={
                "semantic_failover": secondary.provider_name,
                "semantic_primary_status": self.primary.last_status,
                "semantic_remaining_s": round(remaining, 3),
            },
        )
        hand_over_model(secondary.model, secondary.provider_name)
        self.last_provider = "secondary"
        return self.secondary.analyze(context)
