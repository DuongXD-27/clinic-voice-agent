"""Edge case có tên — chỉ có ở sim. Dựng một lần ở đây, cả team dùng lại.

    clinic = scenarios.build("slot_race")                 # sim mặc định + tình huống
    scenarios.apply(clinic, "version_drift")              # chồng thêm lên sim có sẵn
    scenarios.build("terminal_status", status="TRANSFERRED")

`in_real_mock=True`: mock thật tái hiện được tình huống này (contract test chạy được cả `live`).
Thêm scenario mới: viết hàm `(sim, **params) -> None`, đăng ký vào `SCENARIOS`, viết test trong
`tests/clinic_mock_sim/test_scenarios.py`, cập nhật bảng trong README.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from clinic_mock_sim.errors import clinic_error
from clinic_mock_sim.routes import FakeClinicAPI
from clinic_mock_sim.store import DEFAULT_APPOINTMENT, DEFAULT_PATIENT

APPOINTMENT_ID = DEFAULT_APPOINTMENT["appointment_id"]
PHONE = DEFAULT_PATIENT["phone"]

# duplicate_phone: người thứ hai dùng chung số 0912345600
DUPLICATE_PATIENT = {
    "patient_id": "pt_3392",
    "display_name": "N. T. B.",
    "phone": PHONE,
    "dob": "1980-07-21",
    "verify": {"full_name": "Nguyễn Thị B", "dob": "1980-07-21"},
}
# verify_null: số riêng, hồ sơ không có khối verify
VERIFY_NULL_PHONE = "0912345611"
VERIFY_NULL_PATIENT = {
    "patient_id": "pt_4000",
    "display_name": "T. V. C.",
    "phone": VERIFY_NULL_PHONE,
    "dob": "1990-01-01",
    "verify": None,
}
MANY_SLOTS_START = "2026-10-15T07:00:00+07:00"


@dataclass(frozen=True)
class Scenario:
    name: str
    apply: Callable[..., None]
    in_real_mock: bool
    summary: str


def _duplicate_phone(sim: FakeClinicAPI) -> None:
    """2 bệnh nhân cùng số 0912345600 (pt_3391 + pt_3392) → /patients trả 2 bản ghi."""
    sim.seed_patient(DUPLICATE_PATIENT)


def _verify_null(sim: FakeClinicAPI) -> None:
    """pt_4000 số 0912345611 có `verify: null`; đặt lịch cho người này → 500 như mock."""
    sim.seed_patient(VERIFY_NULL_PATIENT)


def _many_slots(sim: FakeClinicAPI, count: int = 150, clinic_id: str = "cl_vinmec") -> None:
    """`count` slot trống ngày 15/10/2026 cách nhau 5 phút từ 07:00 — mặc định 150 > 1 trang (100)."""
    first = datetime.fromisoformat(MANY_SLOTS_START)
    for index in range(count):
        start = first + timedelta(minutes=5 * index)
        sim.seed_slot(
            {
                "slot_id": f"slot_m{index:03d}",
                "clinic_id": clinic_id,
                "start_time": start.isoformat(),
            }
        )


def _slot_race(sim: FakeClinicAPI) -> None:
    """Ngay sau lần đọc /slots kế tiếp, slot đầu tiên vừa trả về bị người khác lấy mất.

    Bot chọn slot đó để đổi/đặt lịch → reschedule 409 SLOT_TAKEN, create 404 NOT_FOUND.
    """

    def take_first(page: dict[str, Any]) -> None:
        if page["data"]:
            sim.take_slot(page["data"][0]["slot_id"])

    sim.after_next("get_slots", take_first)


def _version_drift(sim: FakeClinicAPI, appointment_id: str = APPOINTMENT_ID) -> None:
    """Ngay sau lần đọc lịch kế tiếp, người khác sửa lịch → lệnh ghi đầu tiên VERSION_CONFLICT."""
    sim.after_next("get_appointment", lambda _appt: sim.bump_version(appointment_id))


def _terminal_status(
    sim: FakeClinicAPI, status: str = "CANCELLED", appointment_id: str = APPOINTMENT_ID
) -> None:
    """Lịch đã ở trạng thái cuối trước cuộc gọi → mọi lệnh ghi INVALID_STATE_TRANSITION."""
    sim.set_status(appointment_id, status)


def _write_timeout_applied(sim: FakeClinicAPI, operation: str = "confirm_appointment") -> None:
    """Lệnh ghi `operation` kế tiếp: clinic đã ghi nhưng bot nhận timeout (outcome_known=False)."""
    sim.fail_next(operation, outcome_unknown=True, apply_first=True)


def _upstream_down(sim: FakeClinicAPI, operation: str = "*") -> None:
    """Mọi lần gọi trả 503 UPSTREAM (outcome_known=False như client thật) cho tới `clear_faults()`."""
    sim.fail_always(operation, clinic_error(503, "UPSTREAM", "upstream down"))


def _rate_limited(sim: FakeClinicAPI, operation: str = "*", times: int = 1) -> None:
    """`times` lần gọi kế tiếp trả 429 RATE_LIMITED, sau đó bình thường."""
    sim.fail_times(operation, times, clinic_error(429, "RATE_LIMITED", "rate limited"))


def _bad_key(sim: FakeClinicAPI) -> None:
    """Sai CLINIC_MOCK_API_KEY: mọi lần gọi 401 BAD_KEY."""
    sim.fail_always("*", clinic_error(401, "BAD_KEY", "Invalid bearer token."))


def _slow_backend(sim: FakeClinicAPI, seconds: float = 7.5, operation: str = "*") -> None:
    """Mọi lần gọi chậm `seconds` giây (mặc định sát ngân sách 8 s/lượt). Chờ THẬT bằng `sim.sleep`."""
    sim.delay(operation, seconds)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in [
        Scenario("duplicate_phone", _duplicate_phone, False, "2 bệnh nhân cùng số điện thoại"),
        Scenario("verify_null", _verify_null, False, "Patient không có verify"),
        Scenario("many_slots", _many_slots, False, "Nhiều slot, ép phân trang"),
        Scenario("slot_race", _slot_race, True, "Slot bị lấy giữa get_slots và lệnh ghi"),
        Scenario("version_drift", _version_drift, True, "Version đổi giữa đọc và ghi"),
        Scenario("terminal_status", _terminal_status, True, "Lịch đã ở trạng thái cuối"),
        Scenario("write_timeout_applied", _write_timeout_applied, False, "Timeout nhưng đã ghi"),
        Scenario("upstream_down", _upstream_down, False, "503 mọi lần gọi"),
        Scenario("rate_limited", _rate_limited, False, "429 lần gọi kế tiếp"),
        Scenario("bad_key", _bad_key, False, "401 mọi lần gọi"),
        Scenario("slow_backend", _slow_backend, False, "Độ trễ sát 8 s"),
    ]
}


def apply(sim: FakeClinicAPI, name: str, **params: Any) -> FakeClinicAPI:
    """Chồng scenario `name` lên `sim` có sẵn; trả lại chính `sim` để viết liền một dòng."""
    try:
        scenario = SCENARIOS[name]
    except KeyError:
        raise ValueError(f"Scenario không tồn tại: {name!r}. Có: {sorted(SCENARIOS)}") from None
    scenario.apply(sim, **params)
    return sim


def build(name: str, base: Optional[FakeClinicAPI] = None, **params: Any) -> FakeClinicAPI:
    """Sim mới (mặc định `FakeClinicAPI()`) đã dựng sẵn scenario `name`."""
    return apply(base if base is not None else FakeClinicAPI(), name, **params)
