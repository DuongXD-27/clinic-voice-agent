"""Chẩn đoán của một lượt cho trang demo — KHÔNG chứa PII.

Chỉ gồm nhãn trong danh sách kiểm soát: nguồn / provenance của extraction, `question_id`, lý do chuyển
máy đã YÊU CẦU (không phải bằng chứng chuyển thành công), nhóm lỗi và mã lỗi. Không có transcript,
span, nội dung exception hay body phản hồi Clinic. Giá trị ngoài danh sách bị thay bằng `UNKNOWN` /
bỏ đi, nên dữ liệu đọc lại từ phiên cũ hay từ exception lạ cũng không lọt ra ngoài.
"""

from dataclasses import asdict, dataclass
from typing import Any, Optional, get_args

from callbot.engine.extraction.schema import QuestionId
from callbot.engine.types import TransferReason

EXTRACTION_SOURCES = frozenset({"RULE", "NER", "LLM", "NONE"})
EXTRACTION_PROVENANCES = frozenset({"EXACT", "NORMALIZED", "FALLBACK", "NONE"})
_QUESTION_IDS = frozenset(q.value for q in QuestionId)
_TRANSFER_REASONS = frozenset(get_args(TransferReason))

# Nhóm lỗi cố định
ERROR_TYPES = frozenset(
    {
        "APPOINTMENT_NOT_ACTIONABLE",
        "CLINIC_INVALID_RESPONSE",
        "CLINIC_TERMINATION_FAILED",
        "RECONCILIATION_REQUIRED",
        "SESSION_STORE",
        "GUARDRAIL",
        "CLINIC_REJECTED",
        "CLINIC_ERROR",
        "INTERNAL",
    }
)
# Mã lỗi được phép ra ngoài: mã Clinic mock / client, mã guardrail, mã lỗi HTTP của engine
ERROR_CODES = frozenset(
    {
        # Clinic mock (Phụ lục A + bản mentor)
        "VERSION_CONFLICT",
        "INVALID_STATE_TRANSITION",
        "SLOT_TAKEN",
        "CONFIRMATION_REQUIRED",
        "IDEMPOTENCY_CONFLICT",
        "NOT_FOUND",
        "INVALID_REQUEST",
        "FORBIDDEN",
        "BAD_KEY",
        "METHOD_NOT_ALLOWED",
        "RATE_LIMITED",
        "UPSTREAM",
        "INTERNAL_ERROR",
        # Client HTTP / Gateway
        "TIMEOUT",
        "CONNECT_ERROR",
        "TRANSPORT_ERROR",
        "BAD_RESPONSE",
        "PAGINATION_OVERFLOW",
        # Guardrails
        "SF-01",
        "SF-02",
        "SF-03",
        "SF-04",
        "SF-05",
        # Engine
        "APPOINTMENT_NOT_ACTIONABLE",
        "CLINIC_INVALID_RESPONSE",
        "CLINIC_TERMINATION_FAILED",
        "CALL_RECONCILIATION_REQUIRED",
        "SESSION_STORE_UNAVAILABLE",
        "UNKNOWN",
    }
)
_TRACE_META = frozenset({"turn", "question_id", "transcript", "silent"})


@dataclass(frozen=True)
class TurnDiagnostics:
    question_id: Optional[str] = None
    extraction_source: str = "NONE"
    extraction_provenance: str = "NONE"
    transfer_reason: Optional[str] = None
    error_type: Optional[str] = None
    error_code: Optional[str] = None

    def __post_init__(self) -> None:
        # Lọc ngay khi tạo: mọi đường (lượt mới, phiên cũ, exception) đều qua cùng một chốt
        set_ = object.__setattr__
        if self.question_id not in _QUESTION_IDS:
            set_(self, "question_id", None)
        if self.extraction_source not in EXTRACTION_SOURCES:
            set_(self, "extraction_source", "NONE")
        if self.extraction_provenance not in EXTRACTION_PROVENANCES:
            set_(self, "extraction_provenance", "NONE")
        if self.transfer_reason not in _TRANSFER_REASONS:
            set_(self, "transfer_reason", None)
        if self.error_type is not None and self.error_type not in ERROR_TYPES:
            set_(self, "error_type", "INTERNAL")
        if self.error_code is not None and self.error_code not in ERROR_CODES:
            set_(self, "error_code", "UNKNOWN")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional["TurnDiagnostics"]:
        if not isinstance(data, dict):
            return None
        return cls(**{name: data.get(name) for name in cls.__dataclass_fields__})

    def with_error(self, error: BaseException) -> "TurnDiagnostics":
        error_type, error_code = classify_error(error)
        return TurnDiagnostics(
            **{**asdict(self), "error_type": error_type, "error_code": error_code}
        )


def summarize_extraction(extraction: Optional[dict[str, Any]]) -> tuple[Optional[str], str, str]:
    """(question_id, source, provenance) từ trace extraction — không đọc giá trị hay span."""
    question_id = extraction.get("question_id") if extraction else None
    fields = {
        name: field.get("provenance")
        for name, field in (extraction or {}).items()
        if name not in _TRACE_META and isinstance(field, dict)
    }
    provenances = list(fields.values())
    if any(fields.get(name) == "FALLBACK" for name in ("full_name", "dob")):
        return question_id, "NER", "FALLBACK"
    if "FALLBACK" in provenances:
        # Ý định / đồng ý / lý do hủy từ tầng ngữ nghĩa hoặc fallback LLM — không phải NER tên
        return question_id, "LLM", "FALLBACK"
    for provenance in ("EXACT", "NORMALIZED"):
        if provenance in provenances:
            return question_id, "RULE", provenance
    return question_id, "NONE", "NONE"


def build_diagnostics(
    extraction: Optional[dict[str, Any]],
    *,
    transfer_reason: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> TurnDiagnostics:
    question_id, source, provenance = summarize_extraction(extraction)
    diagnostics = TurnDiagnostics(question_id, source, provenance, transfer_reason)
    return diagnostics.with_error(error) if error is not None else diagnostics


def classify_error(error: BaseException) -> tuple[str, str]:
    """(nhóm lỗi, mã lỗi) — chỉ dựa vào kiểu và mã có kiểm soát, không đọc message."""
    from callbot.engine.errors import (
        CallTerminated,
        ClinicAPIError,
        ClinicWriteRejected,
        ReconciliationRequired,
        SessionStoreUnavailable,
        WriteOutcomeUnknown,
    )
    from callbot.engine.policy.guardrails import SevereFailureBlocked

    if isinstance(error, CallTerminated):
        return error.code, error.cause_code or error.code
    if isinstance(error, (WriteOutcomeUnknown, ReconciliationRequired)):
        return "RECONCILIATION_REQUIRED", "CALL_RECONCILIATION_REQUIRED"
    if isinstance(error, SessionStoreUnavailable):
        return "SESSION_STORE", "SESSION_STORE_UNAVAILABLE"
    if isinstance(error, SevereFailureBlocked):
        return "GUARDRAIL", error.code
    if isinstance(error, ClinicWriteRejected):
        return "CLINIC_REJECTED", error.code or "UNKNOWN"
    if isinstance(error, ClinicAPIError):
        return "CLINIC_ERROR", error.code or "UNKNOWN"
    return "INTERNAL", "UNKNOWN"
