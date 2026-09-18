"""Chuẩn hóa dữ liệu thô của mock sang khóa canonical mà engine đọc (F-05 §5.3).

Chỉ đổi tên/ép kiểu, không suy diễn: không bịa `verify` từ `display_name`, không đoán trạng thái.
Dict phẳng để Session (F-03) tuần tự hóa được và Dialogue/IE của A đọc `starts_at`, `slot_id` như cũ.

Số điện thoại KHÔNG chuẩn hóa ở đây — Verifier làm trước khi tra cứu (T-01).
"""

from datetime import date, datetime
from typing import Any, Optional

from callbot.engine.errors import ClinicAPIError
from callbot.engine.extraction.schema import to_local


def iso_local(moment: datetime) -> str:
    """`from`/`to` của GET /slots: RFC 3339 đủ giây và offset, ví dụ 2026-10-14T00:00:00+07:00."""
    return to_local(moment).replace(microsecond=0).isoformat()


def parse_iso_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_slot(raw: dict[str, Any]) -> dict[str, Any]:
    """Mock trả `start_time`/`end_time`; engine và IE đọc `starts_at`/`ends_at`. Giữ nguyên khóa gốc."""
    slot = dict(raw)
    starts_at = slot.get("starts_at") or slot.get("start_time")
    if not slot.get("slot_id") or not starts_at:
        raise ClinicAPIError(None, "BAD_RESPONSE", "Slot thiếu slot_id hoặc start_time")
    slot["starts_at"] = starts_at
    ends_at = slot.get("ends_at") or slot.get("end_time")
    if ends_at:
        slot["ends_at"] = ends_at
    return slot


def normalize_patient_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    """Ứng viên inbound — đúng ba giá trị luồng nghiệp vụ giữ trong Session: mã, họ tên chuẩn, ngày sinh chuẩn.

    `verifiable=False` khi hồ sơ không có `verify` hợp lệ: Verifier coi là không khớp (fail-closed).
    Không giữ `phone`/`display_name`: không dùng để đối chiếu, giữ thêm chỉ tăng bề mặt rò rỉ.
    """
    patient_id = raw.get("patient_id")
    if not patient_id:
        raise ClinicAPIError(None, "BAD_RESPONSE", "Patient thiếu patient_id")
    verify = raw.get("verify")
    full_name = verify.get("full_name") if isinstance(verify, dict) else None
    dob = parse_iso_date(verify.get("dob")) if isinstance(verify, dict) else None
    return {
        "patient_id": patient_id,
        "full_name": full_name if isinstance(full_name, str) and full_name.strip() else None,
        "dob": dob.isoformat() if dob else None,
        "verifiable": bool(full_name) and dob is not None,
    }


def normalize_appointment(raw: dict[str, Any]) -> dict[str, Any]:
    """Listing 3 giữ nguyên khóa; ép `version`/`attempt_count` về int; `patient.verify` là dict hoặc None."""
    appointment = dict(raw)
    for key in ("appointment_id", "status", "version"):
        if appointment.get(key) in (None, ""):
            raise ClinicAPIError(None, "BAD_RESPONSE", f"Appointment thiếu {key}")
    appointment["version"] = int(appointment["version"])
    appointment["attempt_count"] = int(appointment.get("attempt_count") or 0)
    patient = dict(appointment.get("patient") or {})
    verify = patient.get("verify")
    patient["verify"] = dict(verify) if isinstance(verify, dict) else None
    appointment["patient"] = patient
    return appointment
