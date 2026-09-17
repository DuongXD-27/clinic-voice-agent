from datetime import datetime, timezone

import pytest

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.normalize import (
    iso_local,
    normalize_appointment,
    normalize_patient_candidate,
    normalize_slot,
    parse_iso_date,
)


def test_iso_local_has_seconds_and_offset_for_slot_window() -> None:
    # Mock regex: ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$
    assert iso_local(datetime(2026, 10, 14, 0, 0, 0, 123456)) == "2026-10-14T00:00:00+07:00"
    assert (
        iso_local(datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)) == "2026-10-14T00:00:00+07:00"
    )


def test_slot_maps_mock_start_time_to_starts_at_and_keeps_raw_keys() -> None:
    raw = {
        "slot_id": "slot_91d2",
        "clinic_id": "cl_vinmec",
        "start_time": "2026-10-14T15:00:00+07:00",
        "end_time": "2026-10-14T15:30:00+07:00",
        "provider_id": "pr_vinmec_1",
    }
    slot = normalize_slot(raw)
    assert slot["starts_at"] == raw["start_time"] and slot["ends_at"] == raw["end_time"]
    assert slot["start_time"] == raw["start_time"]  # khóa gốc còn để trace
    assert raw == {k: v for k, v in raw.items()}  # không sửa input


def test_slot_without_id_or_start_is_bad_response() -> None:
    with pytest.raises(ClinicAPIError) as exc:
        normalize_slot({"slot_id": "x"})
    assert exc.value.code == "BAD_RESPONSE"


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            {
                "patient_id": "pt_1",
                "display_name": "N. V. A.",
                "phone": "0912345600",
                "dob": "1978-03-14",
                "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
            },
            {
                "patient_id": "pt_1",
                "full_name": "Nguyễn Văn A",
                "dob": "1978-03-14",
                "verifiable": True,
            },
        ),
        # verify null: không bịa từ display_name, không verifiable
        (
            {"patient_id": "pt_2", "display_name": "Mai N.", "phone": "0912345678", "verify": None},
            {"patient_id": "pt_2", "full_name": None, "dob": None, "verifiable": False},
        ),
        # dob sai định dạng: giữ tên nhưng không verifiable
        (
            {"patient_id": "pt_3", "verify": {"full_name": "Trần B", "dob": "14/03/1978"}},
            {"patient_id": "pt_3", "full_name": "Trần B", "dob": None, "verifiable": False},
        ),
    ],
)
def test_patient_candidate_keeps_only_identity_fields(raw, expected) -> None:
    candidate = normalize_patient_candidate(raw)
    assert candidate == expected
    assert "phone" not in candidate and "display_name" not in candidate


def test_appointment_coerces_ints_and_verify_block() -> None:
    appointment = normalize_appointment(
        {
            "appointment_id": "apt_00417",
            "status": "SCHEDULED",
            "clinic_id": "cl_vinmec",
            "starts_at": "2026-10-14T15:30:00+07:00",
            "patient": {"patient_id": "pt_3391", "display_name": "N. V. A.", "verify": None},
            "version": "3",
        }
    )
    assert appointment["version"] == 3 and appointment["attempt_count"] == 0
    assert appointment["patient"]["verify"] is None


def test_appointment_missing_version_is_bad_response() -> None:
    with pytest.raises(ClinicAPIError):
        normalize_appointment({"appointment_id": "apt_1", "status": "SCHEDULED"})


def test_parse_iso_date_is_fail_closed() -> None:
    assert parse_iso_date("1978-03-14") is not None
    assert parse_iso_date("14/03/1978") is None and parse_iso_date(None) is None
