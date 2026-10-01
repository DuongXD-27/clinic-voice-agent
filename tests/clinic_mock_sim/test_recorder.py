"""The simulator records conditional writes like ClinicMockClient."""

import pytest

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.telemetry import collect_api_calls
from clinic_mock_sim import FakeClinicAPI, clinic_error

APPOINTMENT = "apt_00417"
WRITES = [
    ("confirm_appointment", (APPOINTMENT,), {}),
    ("cancel_appointment", (APPOINTMENT, "COST"), {"confirmed": True}),
    ("transfer_appointment", (APPOINTMENT, "PATIENT_REQUEST"), {}),
    ("reschedule_appointment", (APPOINTMENT, "slot_91d2"), {}),
    ("mark_unreachable", (APPOINTMENT, "NO_ANSWER"), {}),
]


@pytest.mark.parametrize("operation,args,kwargs", WRITES)
@pytest.mark.parametrize("version", [3, None])
@pytest.mark.parametrize("outcome", ["ok", "rejected", "unknown"])
def test_conditional_write_records_if_match(operation, args, kwargs, version, outcome):
    clinic = FakeClinicAPI()
    if outcome != "ok":
        error = (
            clinic_error(409, "VERSION_CONFLICT")
            if outcome == "rejected"
            else clinic_error(None, "TIMEOUT", outcome_known=False)
        )
        clinic.fail_next(operation, error)

    with collect_api_calls() as records:
        if outcome == "ok":
            getattr(clinic, operation)(*args, version, "synthetic-key", **kwargs)
        else:
            with pytest.raises(ClinicAPIError):
                getattr(clinic, operation)(*args, version, "synthetic-key", **kwargs)

    assert records == clinic.calls
    assert len(records) == 1
    assert records[0].if_match_used is (version is not None)
    assert records[0].to_dict()["if_match_used"] is (version is not None)
    assert records[0].outcome == outcome


def test_reads_and_creation_record_no_if_match():
    clinic = FakeClinicAPI()
    with collect_api_calls() as records:
        clinic.find_patient_by_phone("0912345600")
        clinic.get_appointment(APPOINTMENT)
        clinic.get_slots("cl_vinmec", "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00")
        clinic.create_appointment("pt_3391", "slot_aa01", "synthetic-key")

    assert records == clinic.calls
    assert len(records) == 4
    assert all(record.if_match_used is False for record in records)


def test_idempotent_replay_records_if_match_on_each_attempt():
    clinic = FakeClinicAPI()
    with collect_api_calls() as records:
        clinic.confirm_appointment(APPOINTMENT, 3, "synthetic-key")
        clinic.confirm_appointment(APPOINTMENT, 3, "synthetic-key")

    assert len(clinic.writes) == 1
    assert len(records) == 2
    assert all(record.if_match_used is True for record in records)
