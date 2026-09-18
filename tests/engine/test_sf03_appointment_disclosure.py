from copy import deepcopy
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from callbot.engine import BotAction
from tests.engine.fake_clinic import FakeClinicAPI
from tests.engine.identity_cases import (
    CORRECT_DOB,
    IDENTITY_CASES,
    IdentityCase,
    IdentityTurn,
    PromptKind,
)
from tests.engine.test_identity import (
    APPOINTMENT_ID,
    _assert_open_question,
    assert_no_appointment_disclosure,
)


@dataclass(frozen=True)
class SF03Case:
    id: str
    turns: tuple[IdentityTurn, ...] = ()
    alternate_turns: tuple[IdentityTurn, ...] = ()
    identity_failure: bool = False


def _identity_case(case_id: str) -> IdentityCase:
    return next(case for case in IDENTITY_CASES if case.id == case_id)


def _prepare_sf03_clinic(clinic: FakeClinicAPI) -> None:
    """Populate every SF-03 protected appointment field with a distinct canary."""
    clinic.appointments[APPOINTMENT_ID].update(
        clinic_name="Vinmec Central Park",
        ends_at="2026-10-14T16:15:00+07:00",
        cancel_reason="PATIENT_REQUESTED",
        confirmed_at="2026-09-30T08:05:00+07:00",
        new_slot_id="slot_private_1530",
    )


def _request(text: str, expected_prompt: PromptKind = "name") -> IdentityTurn:
    return IdentityTurn(text, "AWAITING_IDENTITY", expected_prompt)


# Reuse the reviewed Identity scenarios for partial verification and terminal mismatch paths.
_TC_ID_02 = _identity_case("TC_ID_02")
_TC_ID_03 = _identity_case("TC_ID_03")
_TC_ID_04 = _identity_case("TC_ID_04")
_TC_ID_05 = _identity_case("TC_ID_05")


SF03_PREVERIFICATION_CASES = (
    SF03Case(id="TC_SF03_01"),
    SF03Case(id="TC_SF03_02", turns=_TC_ID_05.turns),
    SF03Case(id="TC_SF03_03", turns=(_request(CORRECT_DOB),)),
    SF03Case(id="TC_SF03_04", turns=(_request("Tôi có lịch khám ở khoa nào?"),)),
    SF03Case(id="TC_SF03_05", turns=(_request("Lịch khám của tôi vào ngày nào, mấy giờ?"),)),
    SF03Case(id="TC_SF03_06", turns=(_request("Lịch hẹn của tôi đã xác nhận chưa?"),)),
    SF03Case(
        id="TC_SF03_07",
        turns=_TC_ID_02.turns,
        alternate_turns=_TC_ID_03.turns,
        identity_failure=True,
    ),
    SF03Case(id="TC_SF03_08", turns=_TC_ID_04.turns, identity_failure=True),
)


def _start(client: TestClient, call_id: str, appointment_id: str = APPOINTMENT_ID) -> dict:
    response = client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": "outbound",
            "appointment_id": appointment_id,
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _turn(client: TestClient, call_id: str, turn: int, text: str) -> dict:
    response = client.post(
        f"/v1/calls/{call_id}/turn",
        json={"turn": turn, "text": text, "silence_ms": 0, "audio_url": None},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _action(client: TestClient, call_id: str, body: dict) -> BotAction:
    session = client.app.state.session_store.get_session(call_id)
    assert session is not None
    return BotAction(
        utterance=body["utterance"],
        state=body["state"],
        ended=body.get("ended", False),
        outcome=body.get("outcome"),
        transfer_reason=session.context.get("transfer_reason"),
        unreachable_reason=session.context.get("unreachable_reason"),
    )


def _run_case(
    case: SF03Case,
    clinic: FakeClinicAPI,
    client: TestClient,
    appointment_id: str = APPOINTMENT_ID,
) -> tuple[list[BotAction], object]:
    opening = _action(client, case.id, _start(client, case.id, appointment_id))
    assert opening.state == "AWAITING_IDENTITY"
    _assert_open_question(opening, "name", clinic)

    actions = [opening]
    for turn_number, expected in enumerate(case.turns, start=1):
        action = _action(
            client,
            case.id,
            _turn(client, case.id, turn_number, expected.caller_text),
        )
        actions.append(action)
        assert action.state == expected.expected_state
        assert action.outcome == expected.expected_outcome
        if action.ended:
            assert (
                clinic.appointments[appointment_id].get("transfer_reason")
                == expected.expected_transfer_reason
            )
        else:
            assert action.transfer_reason == expected.expected_transfer_reason
        if expected.expected_prompt:
            _assert_open_question(action, expected.expected_prompt, clinic)

    session = client.app.state.session_store.get_session(case.id)
    assert session is not None
    return actions, session


@pytest.mark.parametrize("case", SF03_PREVERIFICATION_CASES, ids=lambda case: case.id)
def test_sf03_preverification_transcript(
    case: SF03Case, clinic: FakeClinicAPI, client: TestClient
) -> None:
    _prepare_sf03_clinic(clinic)
    variants = ((case.id, case.turns, APPOINTMENT_ID),)
    if case.alternate_turns:
        alternate_appointment_id = f"{APPOINTMENT_ID}_alternate"
        alternate_appointment = deepcopy(clinic.appointments[APPOINTMENT_ID])
        alternate_appointment["appointment_id"] = alternate_appointment_id
        clinic.seed_appointment(alternate_appointment)
        variants += ((f"{case.id}_wrong_dob", case.alternate_turns, alternate_appointment_id),)

    for call_id, turns, appointment_id in variants:
        variant = SF03Case(call_id, turns, identity_failure=case.identity_failure)
        actions, session = _run_case(variant, clinic, client, appointment_id)

        # Check every bot utterance, including the POST /v1/calls opening and final transfer.
        assert_no_appointment_disclosure(actions, clinic)
        if session.ended:
            assert session.context == {}
        else:
            assert session.context["identity_step"] != "VERIFIED"

        if case.identity_failure:
            final = actions[-1]
            assert final.state == "ENDED"
            assert final.outcome == "TRANSFERRED"
            assert clinic.writes[-1] == (
                appointment_id,
                "TRANSFERRED",
                {"transfer_reason": "IDENTITY_FAILED"},
            )
        else:
            assert clinic.writes == []

    if case.identity_failure:
        assert len(clinic.writes) == len(variants)


def test_tc_sf03_09_identity_prompts_are_open_questions(
    clinic: FakeClinicAPI, client: TestClient
) -> None:
    _prepare_sf03_clinic(clinic)
    call_id = "TC_SF03_09"

    opening = _action(client, call_id, _start(client, call_id))
    _assert_open_question(opening, "name", clinic)

    # TC_ID_05 supplies only the caller-provided name and stops before DOB verification.
    name_turn = _TC_ID_05.turns[0]
    dob_prompt = _action(client, call_id, _turn(client, call_id, 1, name_turn.caller_text))
    _assert_open_question(dob_prompt, "dob", clinic)
    assert_no_appointment_disclosure([opening, dob_prompt], clinic)

    before_verification = client.app.state.session_store.get_session(call_id)
    assert before_verification is not None
    assert before_verification.context["identity_step"] == "ASK_DOB"

    verified = _action(client, call_id, _turn(client, call_id, 2, CORRECT_DOB))
    assert verified.state == "AWAITING_INTENT"
    after_verification = client.app.state.session_store.get_session(call_id)
    assert after_verification is not None
    assert after_verification.context["identity_step"] == "VERIFIED"


def test_tc_sf03_10_natural_language_appointment_leakage(
    clinic: FakeClinicAPI, client: TestClient
) -> None:
    _prepare_sf03_clinic(clinic)
    clinic.appointments[APPOINTMENT_ID]["starts_at"] = "2026-10-14T15:30:00+07:00"

    actual_actions, session = _run_case(
        SF03Case(
            id="TC_SF03_10",
            turns=(_request("Cho tôi biết ngày giờ khám được không?"),),
        ),
        clinic,
        client,
    )
    assert_no_appointment_disclosure(actual_actions, clinic)
    assert session.context["identity_step"] != "VERIFIED"

    # Canary assertions prove the matcher rejects semantic renderings, not only the raw ISO value.
    leaked_renderings = (
        "Lịch khám là 14 tháng 10.",
        "Lịch của anh chị vào ngày 14 tháng 10.",
        "Cuộc hẹn bắt đầu lúc 15 giờ 30.",
        "Thời gian khám là 15 giờ 30 phút.",
        "Anh chị đến lúc 3 giờ 30 chiều.",
        "Hẹn anh chị lúc 3 giờ rưỡi chiều.",
    )
    for utterance in leaked_renderings:
        with pytest.raises(AssertionError, match="protected values disclosed"):
            assert_no_appointment_disclosure(
                [BotAction(utterance, "AWAITING_IDENTITY")],
                clinic,
            )
