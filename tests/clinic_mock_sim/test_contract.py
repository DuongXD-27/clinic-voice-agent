"""Contract test cạnh "API nghiệp vụ" trên FakeClinicAPI.mentor_mock() (giống store.py của mock sau reset).

Không chạy trên clinic mock thật: instance dùng chung, reset/ghi sẽ xóa và đổi dữ liệu của cả team.
Case viết theo dữ liệu đọc được (version, slot_id...), không ghi cứng giờ khám hay id có hậu tố tenant.
"""

from typing import Any
from uuid import uuid4

import pytest

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.ports import ClinicAPI
from clinic_mock_sim import FakeClinicAPI

APPOINTMENT = "apt_00417"
PHONE = "0912345600"
VINMEC = "cl_vinmec"
OCT_FROM, OCT_TO = "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00"
# Bộ per-tenant của mock: c_001 có 2 slot ngày 15-09-2026 (UTC) — đủ để ép phân trang với limit=1
TENANT_CLINIC, TENANT_FROM, TENANT_TO = "c_001", "2026-09-15T00:00:00Z", "2026-09-16T00:00:00Z"


def _key(op: str) -> str:
    return f"contract:{uuid4().hex[:8]}:{op}"


def _error(call, status: int, code: str) -> ClinicAPIError:
    with pytest.raises(ClinicAPIError) as exc:
        call()
    assert (exc.value.status, exc.value.code) == (status, code), exc.value
    assert exc.value.outcome_known is True
    return exc.value


@pytest.fixture
def api() -> ClinicAPI:
    return FakeClinicAPI.mentor_mock()


# --- Đọc -----------------------------------------------------------------------------


def test_get_appointment_has_listing_3_shape(api: ClinicAPI) -> None:
    appointment = api.get_appointment(APPOINTMENT)
    assert appointment["appointment_id"] == APPOINTMENT
    assert appointment["status"] == "SCHEDULED" and appointment["clinic_id"] == VINMEC
    assert isinstance(appointment["version"], int) and isinstance(appointment["attempt_count"], int)
    verify = appointment["patient"]["verify"]
    assert set(verify) >= {"full_name", "dob"} and appointment["patient"]["patient_id"]


def test_unknown_appointment_is_404(api: ClinicAPI) -> None:
    _error(lambda: api.get_appointment("apt_does_not_exist"), 404, "NOT_FOUND")


def test_patients_by_phone_returns_page_of_patients(api: ClinicAPI) -> None:
    page = api.find_patient_by_phone(PHONE)
    assert set(page) == {"data", "next_cursor", "has_more"} and page["has_more"] is False
    assert page["data"] and all(p["patient_id"] and p["phone"] == PHONE for p in page["data"])


@pytest.mark.parametrize("phone", ["+84912345600", "84912345600", "0112345600", "091234560"])
def test_patients_rejects_phone_outside_mock_pattern(api: ClinicAPI, phone: str) -> None:
    _error(lambda: api.find_patient_by_phone(phone), 400, "INVALID_REQUEST")


def test_slots_pagination_with_limit_1_walks_all_records(api: ClinicAPI) -> None:
    first = api.get_slots(TENANT_CLINIC, TENANT_FROM, TENANT_TO, limit=1)
    assert first["has_more"] is True and first["next_cursor"] and len(first["data"]) == 1
    second = api.get_slots(
        TENANT_CLINIC, TENANT_FROM, TENANT_TO, cursor=first["next_cursor"], limit=1
    )
    ids = {first["data"][0]["slot_id"], second["data"][0]["slot_id"]}
    assert len(ids) == 2
    assert all(s["clinic_id"] == TENANT_CLINIC for s in first["data"] + second["data"])
    everything = api.get_slots(TENANT_CLINIC, TENANT_FROM, TENANT_TO)
    assert {s["slot_id"] for s in everything["data"]} >= ids and everything["has_more"] is False


def test_slots_have_mock_shape_with_start_time(api: ClinicAPI) -> None:
    page = api.get_slots(VINMEC, OCT_FROM, OCT_TO)
    assert page["data"]
    for slot in page["data"]:
        assert set(slot) >= {"slot_id", "clinic_id", "start_time", "end_time", "provider_id"}
        assert "starts_at" not in slot  # chuẩn hóa là việc của Gateway, không phải của mock


@pytest.mark.parametrize(
    "from_, to",
    [
        ("2026-10-14", "2026-10-15"),  # thiếu giờ và offset
        (OCT_FROM, OCT_FROM),  # to == from
        (OCT_FROM, "2026-10-29T00:00:00+07:00"),  # 15 ngày
    ],
)
def test_slots_window_validation(api: ClinicAPI, from_: str, to: str) -> None:
    _error(lambda: api.get_slots(VINMEC, from_, to), 400, "INVALID_REQUEST")


# --- Ghi: version, idempotency, lifecycle ------------------------------------------------


def test_confirm_flow_version_idempotency_and_terminal_state(api: ClinicAPI) -> None:
    version = api.get_appointment(APPOINTMENT)["version"]
    key = _key("confirm")

    _error(
        lambda: api.confirm_appointment(APPOINTMENT, version - 1, _key("stale")),
        409,
        "VERSION_CONFLICT",
    )

    confirmed = api.confirm_appointment(APPOINTMENT, version, key)
    assert confirmed["status"] == "CONFIRMED" and confirmed["version"] == version + 1
    assert confirmed["confirmed_via"] == "callbot"
    assert confirmed["confirmed_at"].endswith("Z")  # store.now_iso() của mock: UTC, hậu tố Z

    # Replay cùng key + cùng If-Match: trả lại đúng phản hồi cũ, không tăng version
    replay = api.confirm_appointment(APPOINTMENT, version, key)
    assert replay["version"] == version + 1
    assert api.get_appointment(APPOINTMENT)["version"] == version + 1

    # Cùng key nhưng If-Match khác → payload khác → 422 (mock băm cả if_match cho confirm)
    _error(
        lambda: api.confirm_appointment(APPOINTMENT, version + 1, key), 422, "IDEMPOTENCY_CONFLICT"
    )

    # Hủy cần confirmed=True (SF-05); từ CONFIRMED vẫn hủy được
    _error(
        lambda: api.cancel_appointment(
            APPOINTMENT, "COST", version + 1, _key("c0"), confirmed=False
        ),
        409,
        "CONFIRMATION_REQUIRED",
    )
    cancelled = api.cancel_appointment(APPOINTMENT, "COST", version + 1, _key("c1"), confirmed=True)
    assert cancelled["status"] == "CANCELLED" and cancelled["cancel_reason"] == "COST"

    # CANCELLED là trạng thái cuối
    _error(
        lambda: api.confirm_appointment(APPOINTMENT, version + 2, _key("again")),
        409,
        "INVALID_STATE_TRANSITION",
    )


def test_transfer_writes_reason(api: ClinicAPI) -> None:
    version = api.get_appointment(APPOINTMENT)["version"]
    result = api.transfer_appointment(APPOINTMENT, "PATIENT_REQUEST", version, _key("transfer"))
    assert result["status"] == "TRANSFERRED" and result["transfer_reason"] == "PATIENT_REQUEST"
    assert api.get_appointment(APPOINTMENT)["version"] == version + 1


def test_reschedule_is_atomic_and_releases_old_slot(api: ClinicAPI) -> None:
    before = api.get_appointment(APPOINTMENT)
    version = before["version"]
    _error(
        lambda: api.reschedule_appointment(APPOINTMENT, "slot_does_not_exist", version, _key("r0")),
        409,
        "SLOT_TAKEN",
    )

    open_slots = api.get_slots(VINMEC, OCT_FROM, OCT_TO)["data"]
    target = open_slots[0]["slot_id"]
    result = api.reschedule_appointment(APPOINTMENT, target, version, _key("r1"))
    # Listing 4: response tối giản
    assert set(result) == {"status", "new_slot_id", "released_slot_id", "version"}
    assert result["status"] == "RESCHEDULED" and result["new_slot_id"] == target
    assert result["version"] == version + 1 and result["released_slot_id"]

    after_ids = {s["slot_id"] for s in api.get_slots(VINMEC, OCT_FROM, OCT_TO)["data"]}
    assert target not in after_ids and result["released_slot_id"] in after_ids
    after = api.get_appointment(APPOINTMENT)
    assert after["status"] == "RESCHEDULED" and after["starts_at"] == open_slots[0]["start_time"]
    assert after["starts_at"] != before["starts_at"]


def test_unreachable_increments_once_and_replays_with_stale_if_match(api: ClinicAPI) -> None:
    before = api.get_appointment(APPOINTMENT)
    version, attempts = before["version"], before["attempt_count"]
    key = _key("unreachable")

    first = api.mark_unreachable(APPOINTMENT, "SILENCE", version, key)
    assert first["status"] == "UNREACHABLE" and first["unreachable_reason"] == "SILENCE"
    assert (first["attempt_count"], first["version"]) == (attempts + 1, version + 1)

    # §4.2.5: cùng key, If-Match đã cũ → vẫn phản hồi 200 cũ, attempt_count KHÔNG tăng lần hai
    replay = api.mark_unreachable(APPOINTMENT, "SILENCE", version, key)
    assert replay["attempt_count"] == attempts + 1
    assert api.get_appointment(APPOINTMENT)["attempt_count"] == attempts + 1

    # Key mới với version cũ → VERSION_CONFLICT; đọc lại rồi gửi với version mới → attempt tăng tiếp
    _error(
        lambda: api.mark_unreachable(APPOINTMENT, "VOICEMAIL", version, _key("u2")),
        409,
        "VERSION_CONFLICT",
    )
    second = api.mark_unreachable(APPOINTMENT, "VOICEMAIL", version + 1, _key("u3"))
    assert (second["attempt_count"], second["version"]) == (attempts + 2, version + 2)


def test_create_appointment_books_once_and_consumes_slot(api: ClinicAPI) -> None:
    patient_id = api.find_patient_by_phone(PHONE)["data"][0]["patient_id"]
    slot_id = api.get_slots(VINMEC, OCT_FROM, OCT_TO)["data"][0]["slot_id"]
    key = _key("book")

    created = api.create_appointment(patient_id, slot_id, key)
    assert created["status"] == "BOOKED" and created["version"] == 1
    assert created["patient"]["patient_id"] == patient_id and created["appointment_id"]

    replay = api.create_appointment(patient_id, slot_id, key)
    assert replay["appointment_id"] == created["appointment_id"]  # không tạo bản thứ hai

    remaining = {s["slot_id"] for s in api.get_slots(VINMEC, OCT_FROM, OCT_TO)["data"]}
    assert slot_id not in remaining
    _error(lambda: api.create_appointment(patient_id, slot_id, _key("b2")), 404, "NOT_FOUND")
    _error(lambda: api.create_appointment("pt_nobody", slot_id, _key("b3")), 404, "NOT_FOUND")
    assert api.get_appointment(created["appointment_id"])["status"] == "BOOKED"


def test_write_responses_never_include_harness_fields(api: ClinicAPI) -> None:
    """Sanity: phản hồi nghiệp vụ không rò trường quản trị (tenant_id, slot_id server-side)."""
    appointment: dict[str, Any] = api.get_appointment(APPOINTMENT)
    assert "tenant_id" not in appointment and "slot_id" not in appointment


@pytest.mark.parametrize(
    "write",
    [
        lambda api, v: api.cancel_appointment(APPOINTMENT, "BOGUS", v, _key("e1"), confirmed=True),
        lambda api, v: api.transfer_appointment(APPOINTMENT, "BOGUS", v, _key("e2")),
        lambda api, v: api.mark_unreachable(APPOINTMENT, "BOGUS", v, _key("e3")),
    ],
    ids=["cancel_reason", "transfer_reason", "unreachable_reason"],
)
def test_reason_outside_appendix_a_is_400_and_writes_nothing(api: ClinicAPI, write) -> None:
    before = api.get_appointment(APPOINTMENT)
    _error(lambda: write(api, before["version"]), 400, "INVALID_REQUEST")
    after = api.get_appointment(APPOINTMENT)
    assert (after["status"], after["version"]) == (before["status"], before["version"])
