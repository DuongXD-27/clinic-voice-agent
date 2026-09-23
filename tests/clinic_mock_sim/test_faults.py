"""Gây lỗi, độ trễ và helper dựng tình huống — phần chỉ có ở sim (faults.py, helper trong routes.py)."""

import pytest

from callbot.engine.errors import ClinicAPIError
from clinic_mock_sim import FakeClinicAPI, clinic_error

APPOINTMENT = "apt_00417"


class Boom(Exception):
    pass


def test_clinic_error_marks_5xx_outcome_unknown_like_the_real_client() -> None:
    assert clinic_error(409, "VERSION_CONFLICT").outcome_known is True
    assert clinic_error(None, "CONNECT_ERROR").outcome_known is True
    assert clinic_error(503, "UPSTREAM").outcome_known is False
    assert clinic_error(503, "UPSTREAM", outcome_known=True).outcome_known is True


def test_fail_next_fails_once_then_recovers() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("get_appointment")
    with pytest.raises(ClinicAPIError) as exc:
        clinic.get_appointment(APPOINTMENT)
    assert (exc.value.status, exc.value.code) == (503, "UPSTREAM")
    assert clinic.get_appointment(APPOINTMENT)["appointment_id"] == APPOINTMENT


def test_fail_next_outcome_unknown_is_a_timeout() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("confirm_appointment", outcome_unknown=True)
    with pytest.raises(ClinicAPIError) as exc:
        clinic.confirm_appointment(APPOINTMENT, 3, "k")
    assert (exc.value.status, exc.value.code, exc.value.outcome_known) == (None, "TIMEOUT", False)
    assert clinic.writes == []


def test_apply_first_writes_then_fails_and_replay_returns_the_write() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    with pytest.raises(ClinicAPIError):
        clinic.confirm_appointment(APPOINTMENT, 3, "k")
    assert clinic.writes == [(APPOINTMENT, "CONFIRMED", {})]

    replay = clinic.confirm_appointment(APPOINTMENT, 3, "k")
    assert replay["status"] == "CONFIRMED" and len(clinic.writes) == 1


def test_fail_next_accepts_any_exception_and_records_it_as_unknown() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("get_appointment", Boom())
    with pytest.raises(Boom):
        clinic.get_appointment(APPOINTMENT)
    assert (clinic.calls[-1].code, clinic.calls[-1].outcome) == ("Boom", "unknown")


def test_fail_times_then_recovers() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_times("get_slots", 2, clinic_error(429, "RATE_LIMITED"))
    for _ in range(2):
        with pytest.raises(ClinicAPIError):
            clinic.get_slots("cl_vinmec", "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00")
    assert clinic.get_slots("cl_vinmec", "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00")


def test_wildcard_and_fail_always_until_cleared() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_always("*", clinic_error(401, "BAD_KEY"))
    for call in (
        lambda: clinic.get_appointment(APPOINTMENT),
        lambda: clinic.confirm_appointment(APPOINTMENT, 3, "k"),
    ):
        with pytest.raises(ClinicAPIError) as exc:
            call()
        assert exc.value.code == "BAD_KEY"
    clinic.clear_faults()
    assert clinic.confirm_appointment(APPOINTMENT, 3, "k")["status"] == "CONFIRMED"


def test_one_shot_fault_wins_over_fail_always() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_always("get_appointment", clinic_error(503, "UPSTREAM"))
    clinic.fail_next("get_appointment", clinic_error(404, "NOT_FOUND"))
    with pytest.raises(ClinicAPIError) as first:
        clinic.get_appointment(APPOINTMENT)
    with pytest.raises(ClinicAPIError) as second:
        clinic.get_appointment(APPOINTMENT)
    assert (first.value.code, second.value.code) == ("NOT_FOUND", "UPSTREAM")


def test_unknown_operation_name_is_rejected() -> None:
    clinic = FakeClinicAPI()
    with pytest.raises(ValueError, match="confirm_apointment"):
        clinic.fail_next("confirm_apointment")


def test_delay_sleeps_and_records_latency() -> None:
    clinic = FakeClinicAPI()
    slept: list[float] = []
    clinic.sleep = slept.append
    clinic.delay("get_appointment", 1.5, times=1)

    clinic.get_appointment(APPOINTMENT)
    clinic.get_appointment(APPOINTMENT)

    assert slept == [1.5]
    assert [c.latency_ms for c in clinic.calls] == [1500, 0]


def test_after_next_runs_once_after_a_successful_call() -> None:
    clinic = FakeClinicAPI()
    seen: list[str] = []
    clinic.after_next("get_appointment", lambda appt: seen.append(appt["appointment_id"]))
    clinic.get_appointment(APPOINTMENT)
    clinic.get_appointment(APPOINTMENT)
    assert seen == [APPOINTMENT]


def test_set_status_and_bump_version_prepare_the_state_without_writes() -> None:
    clinic = FakeClinicAPI()
    clinic.set_status(APPOINTMENT, "CANCELLED")
    assert clinic.bump_version(APPOINTMENT) == 4
    appointment = clinic.get_appointment(APPOINTMENT)
    assert (appointment["status"], appointment["version"]) == ("CANCELLED", 4)
    assert clinic.writes == []
    with pytest.raises(ValueError):
        clinic.set_status(APPOINTMENT, "DONE")


def test_take_slot_hides_it_from_slots_and_blocks_writes() -> None:
    clinic = FakeClinicAPI()
    clinic.take_slot("slot_91d2")
    page = clinic.get_slots("cl_vinmec", "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00")
    assert [s["slot_id"] for s in page["data"]] == ["slot_aa01"]
    with pytest.raises(ClinicAPIError) as exc:
        clinic.reschedule_appointment(APPOINTMENT, "slot_91d2", 3, "k")
    assert exc.value.code == "SLOT_TAKEN"
