from copy import deepcopy
from datetime import date, datetime

import pytest

from callbot.engine import BotAction, CallerInput, CallStart, create_orchestrator
from callbot.engine.verification.names import normalize_text, strip_diacritics
from clinic_mock_sim import FakeClinicAPI
from tests.engine.identity_cases import IDENTITY_CASES, IdentityCase, PromptKind

APPOINTMENT_ID = "apt_00417"
PROHIBITED_WRITE_STATUSES = {"CONFIRMED", "CANCELLED", "RESCHEDULED"}


def _searchable(text: str) -> str:
    return strip_diacritics(normalize_text(text))


def _assert_open_question(action: BotAction, kind: PromptKind, clinic: FakeClinicAPI) -> None:
    utterance = _searchable(action.utterance)
    patient = clinic.appointments[APPOINTMENT_ID]["patient"]
    verify = patient["verify"]

    if kind == "name":
        forbidden = (verify["full_name"], patient["display_name"])
        identity_terms = ("ho ten", "ho va ten", "ten day du", "anh chi nao")
        request_terms = ("cho", "xin", "vui long", "dang noi chuyen")
    else:
        forbidden = (verify["dob"], "14/03/1978", "14-03-1978", "14 thang 3 nam 1978")
        identity_terms = ("ngay sinh", "nam sinh", "ngay thang nam sinh")
        request_terms = ("cho", "xin", "vui long", "nhac lai")

    for value in forbidden:
        assert _searchable(value) not in utterance, (
            f"{kind} prompt disclosed stored identity value {value!r}: {action.utterance!r}"
        )
    assert any(term in utterance for term in identity_terms), (
        f"prompt does not ask the caller to provide {kind}: {action.utterance!r}"
    )
    assert any(term in utterance for term in request_terms), (
        f"prompt is not an open request for {kind}: {action.utterance!r}"
    )


def _spoken_datetime_values(value: str) -> tuple[str, ...]:
    """Deterministic renderings that can disclose an ISO appointment timestamp."""
    moment = datetime.fromisoformat(value)
    hour_12 = moment.hour % 12 or 12
    period = "sáng" if moment.hour < 12 else "chiều" if moment.hour < 18 else "tối"
    values = {
        value,
        moment.date().isoformat(),
        moment.strftime("%d/%m/%Y"),
        moment.strftime("%d-%m-%Y"),
        f"{moment.day} tháng {moment.month}",
        f"ngày {moment.day} tháng {moment.month}",
        f"{moment.day} tháng {moment.month} năm {moment.year}",
        f"ngày {moment.day} tháng {moment.month} năm {moment.year}",
        f"{moment.hour}:{moment.minute:02d}",
        f"{moment.hour}h{moment.minute:02d}",
        f"{moment.hour} giờ {moment.minute}",
        f"{moment.hour} giờ {moment.minute} phút",
        f"{hour_12} giờ {moment.minute} {period}",
        f"{hour_12} giờ {moment.minute} phút {period}",
    }
    if moment.minute == 0:
        values.update((f"{moment.hour} giờ", f"{hour_12} giờ {period}"))
    if moment.minute == 30:
        values.add(f"{hour_12} giờ rưỡi {period}")
    return tuple(values)


def _spoken_date_values(value: str) -> tuple[str, ...]:
    parsed = date.fromisoformat(value)
    return (
        value,
        parsed.strftime("%d/%m/%Y"),
        parsed.strftime("%d-%m-%Y"),
        f"{parsed.day} tháng {parsed.month} năm {parsed.year}",
        f"ngày {parsed.day} tháng {parsed.month} năm {parsed.year}",
    )


def _protected_values(clinic: FakeClinicAPI) -> tuple[str, ...]:
    appointment = clinic.appointments[APPOINTMENT_ID]
    patient = appointment["patient"]
    verify = patient["verify"]
    protected = {
        appointment.get("appointment_id"),
        appointment.get("status"),
        appointment.get("clinic_id"),
        appointment.get("clinic_name"),
        appointment.get("department"),
        appointment.get("cancel_reason"),
        appointment.get("new_slot_id"),
        patient.get("patient_id"),
        patient.get("display_name"),
        verify.get("full_name"),
    }

    status_aliases = {
        "SCHEDULED": ("đã lên lịch", "lịch đã đặt"),
        "CONFIRMED": ("đã xác nhận", "lịch đã được xác nhận"),
        "CANCELLED": ("đã hủy", "lịch đã bị hủy"),
        "RESCHEDULED": ("đã đổi lịch", "lịch đã được đổi"),
    }
    protected.update(status_aliases)
    for aliases in status_aliases.values():
        protected.update(aliases)

    for field in ("starts_at", "ends_at", "confirmed_at"):
        field_value = appointment.get(field)
        if field_value:
            protected.update(_spoken_datetime_values(field_value))
    if verify.get("dob"):
        protected.update(_spoken_date_values(verify["dob"]))

    return tuple(value for value in protected if isinstance(value, str) and value)


def assert_no_appointment_disclosure(
    actions_before_verification: list[BotAction], clinic: FakeClinicAPI
) -> None:
    protected = _protected_values(clinic)
    for index, action in enumerate(actions_before_verification):
        utterance = _searchable(action.utterance)
        disclosed = [value for value in protected if _searchable(value) in utterance]
        assert not disclosed, (
            "protected values disclosed before verification: "
            f"utterance[{index}]={action.utterance!r}, state={action.state!r}, "
            f"values={disclosed!r}"
        )


def _assert_appointment_side_effects(
    case: IdentityCase,
    clinic: FakeClinicAPI,
    before: dict,
    final_action: BotAction,
) -> None:
    after = clinic.appointments[APPOINTMENT_ID]
    assert not ({status for _, status, _ in clinic.writes} & PROHIBITED_WRITE_STATUSES)

    if final_action.transfer_reason == "IDENTITY_FAILED":
        # TRANSFERRED is the required audit write. Scheduling and patient data must stay intact.
        for field in (
            "appointment_id",
            "clinic_id",
            "starts_at",
            "department",
            "patient",
            "attempt_count",
        ):
            assert after[field] == before[field], f"{case.id} mutated protected field {field}"
        assert clinic.writes == [
            (APPOINTMENT_ID, "TRANSFERRED", {"transfer_reason": "IDENTITY_FAILED"})
        ]
        assert "cancel_reason" not in after and "new_slot_id" not in after
        return

    assert clinic.writes == []
    assert after == before


def _call_start(case: IdentityCase) -> CallStart:
    if case.direction == "outbound":
        return CallStart(call_id=case.id, direction="outbound", appointment_id=APPOINTMENT_ID)
    return CallStart(
        call_id=case.id,
        direction="inbound",
        caller_number=case.caller_number,
    )


@pytest.mark.parametrize("case", IDENTITY_CASES, ids=lambda case: case.id)
def test_identity(case: IdentityCase) -> None:
    clinic = FakeClinicAPI()
    before = deepcopy(clinic.appointments[APPOINTMENT_ID])
    orchestrator = create_orchestrator(clinic)

    opening = orchestrator.start_call(_call_start(case))
    assert opening.state == "AWAITING_IDENTITY"
    assert opening.outcome is None
    if case.opening_prompt:
        _assert_open_question(opening, case.opening_prompt, clinic)

    actions = [opening]
    for turn_number, expected in enumerate(case.turns, start=1):
        action = orchestrator.handle_turn(
            case.id,
            CallerInput(turn=turn_number, text=expected.caller_text),
        )
        actions.append(action)
        assert action.state == expected.expected_state
        assert action.outcome == expected.expected_outcome
        assert action.transfer_reason == expected.expected_transfer_reason
        if expected.expected_prompt:
            _assert_open_question(action, expected.expected_prompt, clinic)

    first_verified = next(
        (index for index, action in enumerate(actions) if action.state == "AWAITING_INTENT"),
        len(actions),
    )
    assert_no_appointment_disclosure(actions[:first_verified], clinic)

    if case.expected_lookup_phone:
        assert clinic.patient_lookups == [case.expected_lookup_phone]
    else:
        assert clinic.patient_lookups == []

    _assert_appointment_side_effects(case, clinic, before, actions[-1])
