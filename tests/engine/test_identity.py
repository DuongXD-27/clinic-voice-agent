from copy import deepcopy
from datetime import datetime

import pytest

from callbot.engine import BotAction, CallerInput, CallStart, create_orchestrator
from callbot.engine.nlu.normalizer import normalize_text, strip_diacritics
from tests.engine.fake_clinic import FakeClinicAPI
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


def _protected_values(clinic: FakeClinicAPI) -> tuple[str, ...]:
    appointment = clinic.appointments[APPOINTMENT_ID]
    patient = appointment["patient"]
    starts_at = datetime.fromisoformat(appointment["starts_at"])
    return (
        appointment["appointment_id"],
        appointment["clinic_id"],
        appointment["status"],
        appointment["starts_at"],
        starts_at.date().isoformat(),
        starts_at.strftime("%d/%m/%Y"),
        f"{starts_at.day} tháng {starts_at.month}",
        f"{starts_at.hour} giờ sáng",
        appointment["department"],
        patient["patient_id"],
        patient["display_name"],
        patient["verify"]["full_name"],
    )


def assert_no_appointment_disclosure(
    actions_before_verification: list[BotAction], clinic: FakeClinicAPI
) -> None:
    transcript = _searchable("\n".join(action.utterance for action in actions_before_verification))
    disclosed = [value for value in _protected_values(clinic) if _searchable(value) in transcript]
    assert not disclosed, f"protected values disclosed before verification: {disclosed!r}"


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
    _assert_open_question(opening, "name", clinic)

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
