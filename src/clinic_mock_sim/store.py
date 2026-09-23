"""Dữ liệu seed — tương ứng `clinic-mock/src/clinic_mock/store.py`.

Hai bộ dữ liệu:
- `seed_listing3`: giá trị Listing 3 của contract (apt_00417 lúc 09:00, hai slot trống). Test engine hiện có
  ghi cứng các giá trị này — đây là mặc định của `FakeClinicAPI()`.
- `seed_mentor_mock`: y như `seed_default()` của mock sau /_harness/reset (apt_00417 lúc 15:30, một slot
  canonical, cộng bộ per-tenant). Mock gắn hậu tố tenant vào id per-tenant; sim giữ id gốc.

State của sim nằm trên `FakeClinicAPI` (không có `Store` riêng như mock) để test đọc thẳng
`clinic.appointments`, `clinic.writes`...
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clinic_mock_sim.routes import FakeClinicAPI

DEFAULT_CLINIC = "cl_vinmec"
DEFAULT_PROVIDER = "pr_vinmec_1"

# --- Listing 3 (mặc định) ---------------------------------------------------------------

DEFAULT_PATIENT = {
    "patient_id": "pt_3391",
    "display_name": "N. V. A.",
    "phone": "0912345600",
    "dob": "1978-03-14",
    "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
}
DEFAULT_APPOINTMENT = {
    "appointment_id": "apt_00417",
    "status": "SCHEDULED",
    "clinic_id": DEFAULT_CLINIC,
    "starts_at": "2026-10-14T09:00:00+07:00",
    "ends_at": "2026-10-14T09:30:00+07:00",
    "department": "Nội tổng quát",
    "patient": {
        "patient_id": "pt_3391",
        "display_name": "N. V. A.",
        "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
    },
    "attempt_count": 0,
    "version": 3,
}
DEFAULT_APPOINTMENT_SLOT = "slot_77aa"  # mock: slot của apt_00417, không nằm trong danh sách trống
DEFAULT_SLOTS = [
    {"slot_id": "slot_aa01", "start_time": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "slot_91d2", "start_time": "2026-10-14T14:30:00+07:00"},
]

# --- Mock mentor: canonical + per-tenant ------------------------------------------------

CANONICAL_APPOINTMENT_TIMES = {
    "starts_at": "2026-10-14T15:30:00+07:00",
    "ends_at": "2026-10-14T16:00:00+07:00",
}
CANONICAL_SLOTS = [
    {
        "slot_id": "slot_91d2",
        "clinic_id": DEFAULT_CLINIC,
        "start_time": "2026-10-14T15:00:00+07:00",
        "end_time": "2026-10-14T15:30:00+07:00",
        "provider_id": DEFAULT_PROVIDER,
    },
]
MOCK_TENANT_PATIENTS = [
    {
        "patient_id": "p_12345",
        "display_name": "Mai N.",
        "phone": "0912345678",
        "dob": "1985-04-12",
        "verify": {"full_name": "Nguyễn Thị Mai", "dob": "1985-04-12"},
    },
    {
        "patient_id": "p_67890",
        "display_name": "Nam T.",
        "phone": "0987654321",
        "dob": "1972-11-03",
        "verify": {"full_name": "Trần Văn Nam", "dob": "1972-11-03"},
    },
]
MOCK_TENANT_SLOTS = [
    {
        "slot_id": "s_987",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:00:00Z",
        "end_time": "2026-09-15T09:30:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_988",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:30:00Z",
        "end_time": "2026-09-15T10:00:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_1024",
        "clinic_id": "c_002",
        "start_time": "2026-09-15T11:00:00Z",
        "end_time": "2026-09-15T11:30:00Z",
        "provider_id": "pr_789",
    },
]


def seed_listing3(sim: "FakeClinicAPI") -> None:
    sim.seed_patient(DEFAULT_PATIENT)
    sim.seed_appointment(DEFAULT_APPOINTMENT, slot_id=DEFAULT_APPOINTMENT_SLOT)
    for slot in DEFAULT_SLOTS:
        sim.seed_slot(slot)


def seed_mentor_mock(sim: "FakeClinicAPI") -> None:
    sim.seed_patient(DEFAULT_PATIENT)
    sim.seed_appointment(
        dict(DEFAULT_APPOINTMENT, **CANONICAL_APPOINTMENT_TIMES), slot_id=DEFAULT_APPOINTMENT_SLOT
    )
    for slot in CANONICAL_SLOTS:
        sim.seed_slot(slot)
    for patient in MOCK_TENANT_PATIENTS:
        sim.seed_patient(patient)
    for slot in MOCK_TENANT_SLOTS:
        sim.seed_slot(slot)


def normalize_slot(slot: dict[str, Any]) -> dict[str, Any]:
    """Shape mock: slot_id, clinic_id, start_time, end_time, provider_id — không có starts_at.

    Nhận cả shape cũ {"slot_id", "starts_at"}; field thiếu điền mặc định (cl_vinmec, +30 phút).
    """
    start = slot.get("start_time") or slot["starts_at"]
    return {
        "slot_id": slot["slot_id"],
        "clinic_id": slot.get("clinic_id", DEFAULT_CLINIC),
        "start_time": start,
        "end_time": slot.get("end_time") or slot.get("ends_at") or plus_30(start),
        "provider_id": slot.get("provider_id", DEFAULT_PROVIDER),
    }


def plus_30(start: str) -> str:
    return (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()


def now_iso() -> str:
    # store.now_iso() của mock: UTC, mili giây, hậu tố Z
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
