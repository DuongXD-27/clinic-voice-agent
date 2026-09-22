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
    # bộ nhớ của request; không bao giờ vào `failure_record()` hay session store.
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
        """Lỗi tạm thời: cùng request có thể thành công nếu gửi lại (T-12 quyết định có gửi không)."""
        return self.code in RETRYABLE_CLINIC_CODES or (
            self.status is not None and self.status >= 500
        )


# --- Lệnh ghi Clinic --------------------------------------------------------------


class WriteOutcomeUnknown(EngineError):
    """Đã gửi (hoặc có thể đã gửi) lệnh ghi nhưng không biết Clinic có áp dụng hay không."""


class ClinicWriteRejected(EngineError):
    """Clinic trả lỗi xác định: lệnh chắc chắn không được áp dụng.

    `retryable=True` (429, lỗi kết nối trước khi gửi): T-12 có thể thử lại cùng key; mặc định là lỗi cố định.
    """

    def __init__(self, status: Optional[int], code: Optional[str], retryable: bool = False) -> None:
        self.status = status
        self.code = code
        self.retryable = retryable
        super().__init__(f"Clinic từ chối lệnh ghi: {status} {code}")


class SlotTaken(ClinicWriteRejected):
    pass


# --- Cuộc gọi không thể tiếp tục ------------------------------------------------------

# Message cố định theo mã: không nêu trạng thái hay chi tiết lịch (có thể trước khi xác minh danh tính)
TERMINATION_MESSAGES = {
    "APPOINTMENT_NOT_ACTIONABLE": "Lịch hẹn không còn ở trạng thái có thể thao tác",
    "CLINIC_INVALID_RESPONSE": "Clinic API trả dữ liệu lịch hẹn không hợp lệ",
    "CLINIC_TERMINATION_FAILED": "Không ghi được trạng thái kết thúc cuộc gọi lên Clinic",
}


class CallTerminated(EngineError):
    """Lỗi xác định: cuộc gọi dừng, KHÔNG có business outcome và không gọi /transfer thay thế.

    Giữa cuộc gọi, SessionManager lưu `failure_record()` vào phiên; request sau với cùng call_id nhận lại
    đúng lỗi này (`restore`) mà không chạy lại extraction hay gọi Clinic.
    `cause_code`: mã gốc (mã Clinic, SF-xx) — chỉ dùng cho chẩn đoán, transport lọc theo danh sách.
    """

    http_status = 500
    code = "CALL_TERMINATED"

    def __init__(
        self,
        cause_code: Optional[str] = None,
        *,
        transfer_reason: Optional[str] = None,
    ) -> None:
        self.cause_code = cause_code
        self.transfer_reason = transfer_reason
        super().__init__(f"{self.code} ({cause_code})" if cause_code else self.code)

    @property
    def message(self) -> str:
        return TERMINATION_MESSAGES.get(self.code, "Cuộc gọi không thể tiếp tục")

    def failure_record(self) -> dict[str, Any]:
        """Dấu kết thúc lưu trong phiên: chỉ HTTP status, mã lỗi và chẩn đoán đã lọc."""
        return {
            "http_status": self.http_status,
            "code": self.code,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
        }

    @staticmethod
    def restore(record: dict[str, Any]) -> "CallTerminated":
        from callbot.engine.diagnostics import TurnDiagnostics

        kind = _TERMINATIONS.get(record.get("code", ""), CallTerminated)
        error = kind()
        error.diagnostics = TurnDiagnostics.from_dict(record.get("diagnostics"))
        return error


class ClinicInvalidResponse(CallTerminated):
    """Phản hồi đọc lịch thiếu / sai dữ liệu bắt buộc."""

    http_status = 502
    code = "CLINIC_INVALID_RESPONSE"


class AppointmentNotActionable(CallTerminated):
    """Lịch đã ở trạng thái kết thúc hoặc Clinic từ chối vì lifecycle đã thay đổi."""

    http_status = 409
    code = "APPOINTMENT_NOT_ACTIONABLE"


class ClinicTerminationFailed(CallTerminated):
    """/transfer hoặc /unreachable bị từ chối xác định: không được báo đã chuyển máy / không liên lạc được."""

    http_status = 502
    code = "CLINIC_TERMINATION_FAILED"


_TERMINATIONS: dict[str, type[CallTerminated]] = {
    kind.code: kind
    for kind in (AppointmentNotActionable, ClinicInvalidResponse, ClinicTerminationFailed)
}


# Orchestrator không được biến các lỗi này thành chuyển máy SYSTEM_ERROR: chuyển máy là một lệnh
# ghi mới, trong khi lệnh trước chưa rõ kết quả hoặc chưa ghi được nhật ký — hoặc cuộc gọi đã được
# xác định là không thể tiếp tục (CallTerminated), kể cả khi chính lệnh chuyển máy thất bại.
TURN_ABORTING_ERRORS: tuple[type[Exception], ...] = (
    WriteOutcomeUnknown,
    SessionStoreUnavailable,
    ReconciliationRequired,
    CallTerminated,
)
