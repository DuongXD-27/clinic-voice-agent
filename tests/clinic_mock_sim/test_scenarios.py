"""Mỗi scenario trong `clinic_mock_sim.scenarios` dựng đúng tình huống nó mô tả."""

import pytest

from callbot.engine.errors import ClinicAPIError
from clinic_mock_sim import FakeClinicAPI, scenarios
from clinic_mock_sim.scenarios import SCENARIOS, VERIFY_NULL_PHONE

APPOINTMENT = "apt_00417"
PHONE = "0912345600"
OCT_FROM, OCT_TO = "2026-10-14T00:00:00+07:00", "2026-10-16T00:00:00+07:00"


def _error(call) -> ClinicAPIError:
    with pytest.raises(ClinicAPIError) as exc:
        call()
    return exc.value


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_builds_on_the_default_sim(name: str) -> None:
    clinic = scenarios.build(name)
    assert isinstance(clinic, FakeClinicAPI)
    assert SCENARIOS[name].summary and SCENARIOS[name].apply.__doc__


def test_unknown_scenario_lists_the_valid_names() -> None:
    with pytest.raises(ValueError, match="slot_race"):
        scenarios.build("slot_rase")


def test_apply_stacks_on_an_existing_sim() -> None:
    clinic = FakeClinicAPI.mentor_mock()
    assert scenarios.apply(clinic, "duplicate_phone") is clinic
    assert clinic.strict_slot_window is True


def test_duplicate_phone() -> None:
    page = scenarios.build("duplicate_phone").find_patient_by_phone(PHONE)
    assert {p["patient_id"] for p in page["data"]} == {"pt_3391", "pt_3392"}


def test_verify_null() -> None:
    [patient] = scenarios.build("verify_null").find_patient_by_phone(VERIFY_NULL_PHONE)["data"]
    assert patient["verify"] is None


def test_many_slots_needs_more_than_one_page() -> None:
    clinic = scenarios.build("many_slots")
    first = clinic.get_slots("cl_vinmec", OCT_FROM, OCT_TO)
    assert len(first["data"]) == 100 and first["has_more"] is True
    rest = clinic.get_slots("cl_vinmec", OCT_FROM, OCT_TO, cursor=first["next_cursor"])
    assert len(first["data"]) + len(rest["data"]) == 150 + 2  # + 2 slot mặc định


def test_slot_race_takes_the_first_offered_slot() -> None:
    clinic = scenarios.build("slot_race")
    offered = clinic.get_slots("cl_vinmec", OCT_FROM, OCT_TO)["data"][0]["slot_id"]
    assert _error(lambda: clinic.reschedule_appointment(APPOINTMENT, offered, 3, "k")).code == (
        "SLOT_TAKEN"
    )
    assert _error(lambda: clinic.create_appointment("pt_3391", offered, "k2")).code == "NOT_FOUND"


def test_version_drift_conflicts_the_first_write_only() -> None:
    clinic = scenarios.build("version_drift")
    version = clinic.get_appointment(APPOINTMENT)["version"]
    assert _error(lambda: clinic.confirm_appointment(APPOINTMENT, version, "k1")).code == (
        "VERSION_CONFLICT"
    )
    fresh = clinic.get_appointment(APPOINTMENT)["version"]
    assert clinic.confirm_appointment(APPOINTMENT, fresh, "k2")["status"] == "CONFIRMED"


@pytest.mark.parametrize("status", ["CANCELLED", "TRANSFERRED", "RESCHEDULED"])
def test_terminal_status(status: str) -> None:
    clinic = scenarios.build("terminal_status", status=status)
    assert _error(lambda: clinic.confirm_appointment(APPOINTMENT, 3, "k")).code == (
        "INVALID_STATE_TRANSITION"
    )


def test_write_timeout_applied() -> None:
    clinic = scenarios.build("write_timeout_applied", operation="cancel_appointment")
    error = _error(lambda: clinic.cancel_appointment(APPOINTMENT, "COST", 3, "k", confirmed=True))
    assert error.outcome_known is False
    assert clinic.writes == [(APPOINTMENT, "CANCELLED", {"cancel_reason": "COST"})]


@pytest.mark.parametrize(
    "name, status, code, known",
    [
        ("upstream_down", 503, "UPSTREAM", False),
        ("bad_key", 401, "BAD_KEY", True),
        ("rate_limited", 429, "RATE_LIMITED", True),
    ],
)
def test_backend_failures(name: str, status: int, code: str, known: bool) -> None:
    clinic = scenarios.build(name)
    error = _error(lambda: clinic.get_appointment(APPOINTMENT))
    assert (error.status, error.code, error.outcome_known) == (status, code, known)


def test_upstream_down_stays_down_rate_limited_recovers() -> None:
    down, limited = scenarios.build("upstream_down"), scenarios.build("rate_limited")
    _error(lambda: down.get_appointment(APPOINTMENT))
    _error(lambda: down.get_appointment(APPOINTMENT))
    _error(lambda: limited.get_appointment(APPOINTMENT))
    assert limited.get_appointment(APPOINTMENT)["appointment_id"] == APPOINTMENT


def test_slow_backend_delays_every_call() -> None:
    clinic = scenarios.build("slow_backend", seconds=2.0)
    slept: list[float] = []
    clinic.sleep = slept.append
    clinic.get_appointment(APPOINTMENT)
    clinic.find_patient_by_phone(PHONE)
    assert slept == [2.0, 2.0]
