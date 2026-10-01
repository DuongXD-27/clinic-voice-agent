"""Dữ liệu seed — tương ứng `clinic-mock/src/clinic_mock/store.py`.

Hai bộ dữ liệu:
- `seed_listing3`: giá trị Listing 3 của contract (apt_00417 lúc 09:00, hai slot trống). Test engine hiện có
  ghi cứng các giá trị này — đây là mặc định của `FakeClinicAPI()`.
- `seed_mentor_mock`: y như `seed_default()` của mock sau /_harness/reset (apt_00417 lúc 15:30, một slot
  canonical, 10 bệnh nhân demo pt_3401–pt_3410 với lịch apt_00418–apt_00427 và 10 slot trống
  slot_b501–slot_b510, cộng bộ per-tenant). Mock gắn hậu tố tenant vào id per-tenant; sim giữ id gốc.

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
# Bản ghi demo mock thêm ngày 24-09-2026 (clinic-mock `aa8b94e`, mentor cho phép): hồ sơ thường, không
# edge case. Mỗi bệnh nhân một lịch SCHEDULED chiếm slot riêng không nằm trong danh sách trống.
DEMO_PATIENTS = [
    {
        "patient_id": patient_id,
        "display_name": display_name,
        "phone": phone,
        "dob": dob,
        "verify": {"full_name": full_name, "dob": dob},
    }
    for patient_id, display_name, phone, dob, full_name in [
        ("pt_3401", "T. T. B.", "0901234501", "1990-06-21", "Trần Thị Bình"),
        ("pt_3402", "L. V. C.", "0901234502", "1965-01-09", "Lê Văn Cường"),
        ("pt_3403", "P. T. D.", "0901234503", "1988-12-02", "Phạm Thị Dung"),
        ("pt_3404", "H. M. Đ.", "0901234504", "1975-07-30", "Hoàng Minh Đức"),
        ("pt_3405", "V. T. H.", "0901234505", "1995-03-17", "Vũ Thị Hoa"),
        ("pt_3406", "Đ. Q. H.", "0901234506", "1982-09-05", "Đặng Quốc Hùng"),
        ("pt_3407", "B. T. L.", "0901234507", "1970-11-23", "Bùi Thị Lan"),
        ("pt_3408", "Đ. V. L.", "0901234508", "1999-02-14", "Đỗ Văn Long"),
        ("pt_3409", "N. T. M.", "0901234509", "1986-05-08", "Ngô Thị Minh"),
        ("pt_3410", "D. T. P.", "0901234510", "1960-10-01", "Dương Thanh Phong"),
    ]
]
# Sau slot_91d2 theo cả thứ tự lẫn giờ để slot_91d2 vẫn được đề xuất đầu tiên (như mock)
DEMO_SLOTS = [
    {
        "slot_id": slot_id,
        "clinic_id": DEFAULT_CLINIC,
        "start_time": f"{start}:00+07:00",
        "end_time": f"{end}:00+07:00",
        "provider_id": DEFAULT_PROVIDER,
    }
    for slot_id, start, end in [
        ("slot_b501", "2026-10-15T10:30", "2026-10-15T11:00"),
        ("slot_b502", "2026-10-15T15:30", "2026-10-15T16:00"),
        ("slot_b503", "2026-10-16T09:00", "2026-10-16T09:30"),
        ("slot_b504", "2026-10-16T14:00", "2026-10-16T14:30"),
        ("slot_b505", "2026-10-19T10:00", "2026-10-19T10:30"),
        ("slot_b506", "2026-10-19T15:30", "2026-10-19T16:00"),
        ("slot_b507", "2026-10-20T08:00", "2026-10-20T08:30"),
        ("slot_b508", "2026-10-20T14:00", "2026-10-20T14:30"),
        ("slot_b509", "2026-10-21T09:00", "2026-10-21T09:30"),
        ("slot_b510", "2026-10-21T15:00", "2026-10-21T15:30"),
    ]
]
# (appointment_id, slot của lịch, patient_id, bắt đầu, kết thúc, khoa)
DEMO_APPOINTMENTS = [
    ("apt_00418", "slot_a418", "pt_3401", "2026-10-15T08:00", "2026-10-15T08:30", "Nội tổng quát"),
    ("apt_00419", "slot_a419", "pt_3402", "2026-10-15T09:30", "2026-10-15T10:00", "Tim mạch"),
    ("apt_00420", "slot_a420", "pt_3403", "2026-10-15T14:00", "2026-10-15T14:30", "Sản phụ khoa"),
    ("apt_00421", "slot_a421", "pt_3404", "2026-10-16T08:30", "2026-10-16T09:00", "Tiêu hóa"),
    ("apt_00422", "slot_a422", "pt_3405", "2026-10-16T10:00", "2026-10-16T10:30", "Da liễu"),
    ("apt_00423", "slot_a423", "pt_3406", "2026-10-16T15:00", "2026-10-16T15:30", "Cơ xương khớp"),
    ("apt_00424", "slot_a424", "pt_3407", "2026-10-19T08:00", "2026-10-19T08:30", "Mắt"),
    ("apt_00425", "slot_a425", "pt_3408", "2026-10-19T09:00", "2026-10-19T09:30", "Tai Mũi Họng"),
    ("apt_00426", "slot_a426", "pt_3409", "2026-10-19T14:30", "2026-10-19T15:00", "Răng Hàm Mặt"),
    ("apt_00427", "slot_a427", "pt_3410", "2026-10-20T09:00", "2026-10-20T09:30", "Thần kinh"),
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
    for patient in DEMO_PATIENTS:
        sim.seed_patient(patient)
    for slot in DEMO_SLOTS:
        sim.seed_slot(slot)
    patients = {patient["patient_id"]: patient for patient in DEMO_PATIENTS}
    for appointment_id, slot_id, patient_id, start, end, department in DEMO_APPOINTMENTS:
        patient = patients[patient_id]
        sim.seed_appointment(
            {
                "appointment_id": appointment_id,
                "status": "SCHEDULED",
                "clinic_id": DEFAULT_CLINIC,
                "starts_at": f"{start}:00+07:00",
                "ends_at": f"{end}:00+07:00",
                "department": department,
                "patient": {
                    "patient_id": patient_id,
                    "display_name": patient["display_name"],
                    "verify": patient["verify"],
                },
                "version": 1,
            },
            slot_id=slot_id,
        )
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
