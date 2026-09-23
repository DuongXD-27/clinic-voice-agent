"""Cổng tới clinic mock (§4.2) — cạnh "API nghiệp vụ" giữa Clinic Gateway và Clinic Mock.

Protocol mô phỏng mock 1:1: một trang mỗi lần gọi, shape thô của mock, lỗi là `ClinicAPIError`.
Nhờ vậy cùng một bộ contract test chạy được trên `ClinicMockClient` (HTTP thật) và `clinic_mock_sim.FakeClinicAPI`.
Chuẩn hóa sang khóa canonical của engine là việc của `ClinicGateway` (F-05 §5.3), không phải của cổng.

Shape thô (đối chiếu `clinic-mock/src/clinic_mock/schemas.py`):
- Danh sách: `Page` = {"data": [...], "next_cursor": str | None, "has_more": bool}; `limit` mock kẹp [1, 100].
- Patient: patient_id, display_name, phone, dob, verify {full_name, dob} | None.
- Slot: slot_id, clinic_id, start_time, end_time, provider_id  (KHÔNG có starts_at).
- Appointment: Listing 3 + ends_at, cancel_reason, transfer_reason, unreachable_reason,
  confirmed_at, confirmed_via, new_slot_id, attempt_count, version.
- Reschedule trả tối giản: status, new_slot_id, released_slot_id, version.
- Create trả 201 với appointment đầy đủ.
"""

from typing import Any, Optional, Protocol, TypedDict

from callbot.engine.errors import ClinicAPIError

# Mock trả tối đa 100 bản ghi một trang; Gateway đọc hết trang nên xin trang lớn nhất
PAGE_LIMIT = 100


class Page(TypedDict):
    data: list[dict[str, Any]]
    next_cursor: Optional[str]
    has_more: bool


class ClinicAPI(Protocol):
    def find_patient_by_phone(
        self, phone: str, cursor: Optional[str] = None, limit: int = PAGE_LIMIT
    ) -> Page: ...

    def get_slots(
        self,
        clinic_id: str,
        from_: str,
        to: str,
        cursor: Optional[str] = None,
        limit: int = PAGE_LIMIT,
    ) -> Page: ...

    def get_appointment(self, appointment_id: str) -> dict[str, Any]: ...

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]: ...

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]: ...

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]: ...

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def mark_unreachable(
        self,
        appointment_id: str,
        unreachable_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...


def as_page(payload: Any) -> Page:
    """Ép kết quả danh sách về `Page`; shape lạ là lỗi, không đoán khóa (`patients`, `items`...).

    Body rỗng `{}` (stub/transport không có nội dung) coi là trang rỗng — mock thật luôn trả đủ ba khóa.
    """
    if isinstance(payload, dict) and not payload:
        return {"data": [], "next_cursor": None, "has_more": False}
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ClinicAPIError(None, "BAD_RESPONSE", "Danh sách không có khóa `data`")
    return {
        "data": payload["data"],
        "next_cursor": payload.get("next_cursor"),
        "has_more": bool(payload.get("has_more", False)),
    }


__all__ = ["PAGE_LIMIT", "ClinicAPI", "ClinicAPIError", "Page", "as_page"]
