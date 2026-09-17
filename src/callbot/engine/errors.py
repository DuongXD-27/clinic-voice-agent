"""Lỗi mức engine mà transport cần phân biệt (F-03).

Tách khỏi session/ và tools/ để hai package cùng raise mà không import vòng.
"""

from typing import Optional


class EngineError(Exception):
    pass


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


# --- Lệnh ghi Clinic --------------------------------------------------------------


class WriteOutcomeUnknown(EngineError):
    """Đã gửi (hoặc có thể đã gửi) lệnh ghi nhưng không biết Clinic có áp dụng hay không."""


class ClinicWriteRejected(EngineError):
    """Clinic trả lỗi xác định: lệnh chắc chắn không được áp dụng."""

    def __init__(self, status: Optional[int], code: Optional[str]) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Clinic từ chối lệnh ghi: {status} {code}")


class SlotTaken(ClinicWriteRejected):
    pass


# Orchestrator không được biến các lỗi này thành chuyển máy SYSTEM_ERROR: chuyển máy là một lệnh
# ghi mới, trong khi lệnh trước chưa rõ kết quả hoặc chưa ghi được nhật ký.
TURN_ABORTING_ERRORS: tuple[type[Exception], ...] = (
    WriteOutcomeUnknown,
    SessionStoreUnavailable,
    ReconciliationRequired,
)
