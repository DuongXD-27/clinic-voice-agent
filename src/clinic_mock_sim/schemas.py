"""Ràng buộc dữ liệu — tương ứng `clinic-mock/src/clinic_mock/schemas.py`.

Mock kiểm các ràng buộc này bằng pydantic/FastAPI TRƯỚC khi vào route (sai → 400 INVALID_REQUEST),
nên sim cũng kiểm trước idempotency và trước mọi lệnh đọc/ghi state.
"""

import re
from datetime import timedelta

PHONE_RE = re.compile(r"^(02|03|05|07|08|09)\d{8}$")
# RFC 3339 đủ giây; offset `+07:00` hoặc `Z`
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

SLOT_WINDOW_MAX = timedelta(days=14)
PAGE_LIMIT_MIN, PAGE_LIMIT_MAX = 1, 100

# Appendix A của contract
APPOINTMENT_STATUSES = frozenset(
    {"SCHEDULED", "BOOKED", "CONFIRMED", "CANCELLED", "RESCHEDULED", "TRANSFERRED", "UNREACHABLE"}
)
CANCEL_REASONS = frozenset(
    {"PATIENT_UNAVAILABLE", "NO_LONGER_NEEDED", "WENT_ELSEWHERE", "COST", "UNSPECIFIED"}
)
TRANSFER_REASONS = frozenset(
    {
        "IDENTITY_FAILED",
        "PATIENT_NOT_FOUND",
        "OUT_OF_SCOPE",
        "CLINICAL_QUESTION",
        "NOT_UNDERSTOOD",
        "PATIENT_REQUEST",
        "SYSTEM_ERROR",
    }
)
UNREACHABLE_REASONS = frozenset({"SILENCE", "VOICEMAIL", "NO_ANSWER", "LINE_BUSY"})
