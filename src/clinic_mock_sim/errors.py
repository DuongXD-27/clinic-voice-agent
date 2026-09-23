"""Lỗi chuẩn — tương ứng `clinic-mock/src/clinic_mock/errors.py`.

Mock trả envelope {"error": {"code", "message", "request_id"}}; `ClinicMockClient` dịch nó thành
`ClinicAPIError`. Sim raise thẳng `ClinicAPIError` đã dịch, cùng status/code/message với mock.
"""

from typing import Optional

from callbot.engine.errors import ClinicAPIError

REQUEST_ID = "fake"


def clinic_error(
    status: Optional[int],
    code: str,
    message: str = "",
    *,
    outcome_known: Optional[bool] = None,
) -> ClinicAPIError:
    """Lỗi như `ClinicMockClient` trả cho bot; test dùng để giả một lần từ chối.

    `outcome_known` mặc định giống client thật: 5xx → False (không biết mock đã ghi chưa), còn lại True.
    """
    if outcome_known is None:
        outcome_known = not (status is not None and status >= 500)
    return ClinicAPIError(
        status, code, message or code, request_id=REQUEST_ID, outcome_known=outcome_known
    )


def validation_error(message: str = "Request validation failed.") -> ClinicAPIError:
    return clinic_error(400, "INVALID_REQUEST", message)


def not_found(what: str) -> ClinicAPIError:
    return clinic_error(404, "NOT_FOUND", f"{what} not found.")


def conflict(code: str, message: str) -> ClinicAPIError:
    return clinic_error(409, code, message)


def version_conflict() -> ClinicAPIError:
    return conflict("VERSION_CONFLICT", "If-Match version does not match current state.")


def confirmation_required() -> ClinicAPIError:
    return conflict(
        "CONFIRMATION_REQUIRED", "Cancellation requires an explicit second confirmation."
    )


def unprocessable(code: str, message: str) -> ClinicAPIError:
    return clinic_error(422, code, message)


def internal_error() -> ClinicAPIError:
    """500 do pydantic ném trong route (không có envelope) — client thật suy code HTTP_ERROR."""
    return clinic_error(500, "HTTP_ERROR", "Internal Server Error")
