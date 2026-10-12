"""Lỗi mức engine mà transport cần phân biệt (F-03).

Tách khỏi session/ và tools/ để hai package cùng raise mà không import vòng.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from callbot.engine.diagnostics import TurnDiagnostics


class EngineError(Exception):
    # Orchestrator / SessionManager gắn chẩn đoán KHÔNG chứa PII của lượt gây lỗi (transport đọc cho demo)
    diagnostics: Optional["TurnDiagnostics"] = None
    # Lý do chuyển máy đang được ghi khi lỗi xảy ra — chỉ để chẩn đoán, không phải bằng chứng đã chuyển
    transfer_reason: Optional[str] = None
    # Trace extraction của lượt lỗi — CÓ transcript / span, chỉ để trang demo hiển thị. Chỉ sống trong
    # bộ nhớ của request; không bao giờ vào session store.
    extraction: Optional[dict[str, Any]] = None


# --- Phiên và thứ tự lượt ---------------------------------------------------------


class SessionNotFound(EngineError):
    pass


class CallConflict(EngineError):
    """Mở lại `call_id` đã có với cấu hình khác."""


class TurnConflict(EngineError):
    """Cùng số lượt nhưng đầu vào khác lần đã nhận."""


class TurnOutOfOrder(EngineError):
    def __init__(self, call_id: str, turn: int, expected_turn: int) -> None:
        self.expected_turn = expected_turn
        super().__init__(f"{call_id}: nhận lượt {turn}, đang chờ lượt {expected_turn}")


class CallEnded(EngineError):
    """Lượt mới gửi tới phiên đã ENDED."""


class CallBusy(EngineError):
    """Không lấy được khóa phiên trong thời gian chờ."""


class ReconciliationRequired(EngineError):
    """Có lệnh ghi Clinic chưa rõ kết quả — phiên bị chặn tới khi đối soát xong."""

    def __init__(self, call_id: str, turn: Optional[int], detail: str = "") -> None:
        self.turn = turn
        super().__init__(f"{call_id}: lượt {turn} cần đối soát. {detail}".strip())


class SessionStoreUnavailable(EngineError):
    pass


class OutboundStartFailed(EngineError):
    """Không đủ dữ liệu Clinic để mở outbound; chưa có cuộc gọi để chuyển máy."""

    def __init__(self, error_code: Optional[str] = None) -> None:
        self.code = error_code
        super().__init__("Không thể chuẩn bị cuộc gọi outbound")


class CallStartBlocked(EngineError):
    """Output Guard chặn lời mở đầu (R-01 §3.7): chưa tạo phiên, chưa nói gì, chưa ghi Clinic."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Lời mở đầu bị Output Guard chặn ({code})")


# --- Gọi Clinic mock (F-05) ---------------------------------------------------------

# Mã lỗi mock có thể trả (Phụ lục A + mã riêng của bản mentor) và mã do client đặt cho lỗi transport
RETRYABLE_CLINIC_CODES = frozenset({"RATE_LIMITED", "UPSTREAM", "TIMEOUT", "CONNECT_ERROR"})


class ClinicAPIError(EngineError):
    """Một lần gọi API mock thất bại — cùng một kiểu cho client HTTP thật và fake.

    `outcome_known=False`: không biết mock đã áp dụng request chưa (read timeout, 5xx, đứt kết nối
    giữa chừng). Với lệnh đọc điều này không quan trọng; với lệnh ghi Gateway phải coi là chưa rõ.
    """

    def __init__(
        self,
        status: Optional[int],
        code: Optional[str],
        message: str = "",
        request_id: Optional[str] = None,
        outcome_known: bool = True,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.outcome_known = outcome_known
        super().__init__(f"Clinic {status} {code}: {message}".rstrip(": "))

    @property
    def retryable(self) -> bool:
        """Lỗi tạm thời: cùng request có thể thành công nếu gửi lại (Gateway gửi lại có giới hạn, T-12)."""
        return self.code in RETRYABLE_CLINIC_CODES or (
            self.status is not None and self.status >= 500
        )


# --- Lệnh ghi Clinic --------------------------------------------------------------


class WriteOutcomeUnknown(EngineError):
    """Đã gửi (hoặc có thể đã gửi) lệnh ghi nhưng không biết Clinic có áp dụng hay không."""


class ClinicWriteRejected(EngineError):
    """Clinic trả lỗi xác định: lệnh chắc chắn không được áp dụng.

    `retryable=True` (429, lỗi kết nối trước khi gửi): Gateway đã gửi lại cùng key tới giới hạn (T-12)
    mà vẫn lỗi; mặc định là lỗi cố định.
    """

    def __init__(self, status: Optional[int], code: Optional[str], retryable: bool = False) -> None:
        self.status = status
        self.code = code
        self.retryable = retryable
        super().__init__(f"Clinic từ chối lệnh ghi: {status} {code}")


class SlotTaken(ClinicWriteRejected):
    pass


# --- Lịch hẹn không dùng được -----------------------------------------------------------


class AppointmentUnusable(EngineError):
    """Lịch hẹn không dùng được cho thao tác đang làm; gửi lại cũng không khác.

    Không chặn lượt: như mọi lỗi nghiệp vụ, orchestrator chuyển máy SYSTEM_ERROR để nhân viên xử lý.
    `cause_code`: mã gốc (mã Clinic) — chỉ dùng cho chẩn đoán.
    """

    code = "APPOINTMENT_UNUSABLE"

    def __init__(self, cause_code: Optional[str] = None) -> None:
        self.cause_code = cause_code
        super().__init__(f"{self.code} ({cause_code})" if cause_code else self.code)


class ClinicInvalidResponse(AppointmentUnusable):
    """Phản hồi đọc lịch thiếu / sai dữ liệu bắt buộc."""

    code = "CLINIC_INVALID_RESPONSE"


class AppointmentNotActionable(AppointmentUnusable):
    """Lịch đã ở trạng thái kết thúc hoặc Clinic từ chối vì lifecycle đã thay đổi."""

    code = "APPOINTMENT_NOT_ACTIONABLE"


# Orchestrator không được biến các lỗi này thành chuyển máy SYSTEM_ERROR: chuyển máy là một lệnh
# ghi mới, trong khi lệnh trước chưa rõ kết quả, chưa ghi được nhật ký, hoặc khách đã rời cuộc
# gọi (CallEnded từ cổng ghi, R-36).
TURN_ABORTING_ERRORS: tuple[type[Exception], ...] = (
    CallEnded,
    WriteOutcomeUnknown,
    SessionStoreUnavailable,
    ReconciliationRequired,
)
