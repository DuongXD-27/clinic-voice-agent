"""Hành vi routes.py mà contract test không phủ được trên mock thật (dữ liệu mock không có sẵn).

Mỗi case ghi rõ đoạn code mock tương ứng để khi mentor đổi mock, biết case nào phải sửa theo.
"""

import pytest

from callbot.engine.errors import ClinicAPIError
from clinic_mock_sim import FakeClinicAPI, scenarios

APPOINTMENT = "apt_00417"
OCT_FROM, OCT_TO = "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00"


def _code(call) -> tuple:
    with pytest.raises(ClinicAPIError) as exc:
        call()
    return exc.value.status, exc.value.code, exc.value.outcome_known


def test_create_for_patient_without_verify_is_500_and_books_nothing() -> None:
    # routes.create_appointment → _patient_ref(PatientRef(verify=None)) → pydantic lỗi → 500
    clinic = scenarios.build("verify_null")
    assert _code(lambda: clinic.create_appointment("pt_4000", "slot_aa01", "k")) == (
        500,
        "HTTP_ERROR",
        False,
    )
    assert clinic.writes == [] and "slot_aa01" not in clinic.taken_slots


def test_invalid_reason_is_checked_before_idempotency() -> None:
    # FastAPI validate body trước khi vào route: key đã dùng cũng không được replay
    clinic = FakeClinicAPI()
    clinic.cancel_appointment(APPOINTMENT, "COST", 3, "k", confirmed=True)
    assert _code(
        lambda: clinic.cancel_appointment(APPOINTMENT, "BOGUS", 3, "k", confirmed=True)
    ) == (400, "INVALID_REQUEST", True)


def test_reschedule_releases_old_slot_with_the_old_provider() -> None:
    # routes.reschedule_appointment: Slot(..., provider_id=appt.provider_id)
    clinic = FakeClinicAPI(seed=False)
    clinic.seed_appointment(
        {
            "appointment_id": "apt_x",
            "status": "SCHEDULED",
            "clinic_id": "cl_vinmec",
            "starts_at": "2026-10-14T08:00:00+07:00",
            "ends_at": "2026-10-14T08:30:00+07:00",
            "department": "Nội tổng quát",
            "patient": {"patient_id": "pt_1", "display_name": "A", "verify": None},
        },
        slot_id="slot_old",
        provider_id="pr_old",
    )
    clinic.seed_slot(
        {"slot_id": "slot_new", "start_time": "2026-10-14T10:00:00+07:00", "provider_id": "pr_new"}
    )

    result = clinic.reschedule_appointment("apt_x", "slot_new", 1, "k")

    slots = {s["slot_id"]: s for s in clinic.get_slots("cl_vinmec", OCT_FROM, OCT_TO)["data"]}
    assert result["released_slot_id"] == "slot_old" and set(slots) == {"slot_old"}
    assert slots["slot_old"]["provider_id"] == "pr_old"
    assert slots["slot_old"]["start_time"] == "2026-10-14T08:00:00+07:00"


def test_seed_slot_replaces_same_id_and_normalizes_shape() -> None:
    clinic = FakeClinicAPI(seed=False)
    clinic.seed_slot({"slot_id": "s1", "starts_at": "2026-10-14T10:00:00+07:00"})
    clinic.seed_slot({"slot_id": "s1", "start_time": "2026-10-14T11:00:00+07:00"})
    assert clinic.slots == [
        {
            "slot_id": "s1",
            "clinic_id": "cl_vinmec",
            "start_time": "2026-10-14T11:00:00+07:00",
            "end_time": "2026-10-14T11:30:00+07:00",
            "provider_id": "pr_vinmec_1",
        }
    ]


def test_unreachable_can_repeat_but_not_after_confirm() -> None:
    # lifecycle: unreachable từ SCHEDULED/BOOKED; route cho thêm UNREACHABLE → UNREACHABLE
    clinic = FakeClinicAPI()
    clinic.mark_unreachable(APPOINTMENT, "SILENCE", 3, "u1")
    assert clinic.mark_unreachable(APPOINTMENT, "NO_ANSWER", 4, "u2")["attempt_count"] == 2

    confirmed = FakeClinicAPI()
    confirmed.confirm_appointment(APPOINTMENT, 3, "c1")
    assert _code(lambda: confirmed.mark_unreachable(APPOINTMENT, "SILENCE", 4, "u3"))[1] == (
        "INVALID_STATE_TRANSITION"
    )


def test_returned_records_are_copies() -> None:
    clinic = FakeClinicAPI()
    clinic.get_appointment(APPOINTMENT)["patient"]["verify"]["full_name"] = "changed"
    assert clinic.appointments[APPOINTMENT]["patient"]["verify"]["full_name"] == "Nguyễn Văn A"


def test_close_is_recorded() -> None:
    clinic = FakeClinicAPI()
    clinic.close()
    assert clinic.closed is True
