"""AIHR-PC-001 confirm-attendance scoring cases at the public orchestrator/clinic boundary.

The cases deliberately inspect the appointment record and write log after each risky
turn.  Production dialogue and extraction are not patched by this suite.
"""

from copy import deepcopy

import pytest

from callbot.engine import CallEnded, CallerInput, CallStart, create_orchestrator
from callbot.engine.session import CallContext
from clinic_mock_sim import FakeClinicAPI

APPOINTMENT = "apt_00417"
NAME = "Nguyễn Văn A"
DOB = "14/03/1978"
READBACK_PARTS = ("14 tháng 10", "9 giờ", "Vinmec Times City")


def start(case_id: str, clinic: FakeClinicAPI | None = None):
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    opening = bot.start_call(
        CallStart(call_id=case_id, direction="outbound", appointment_id=APPOINTMENT)
    )
    before = deepcopy(clinic.appointments[APPOINTMENT])
    assert opening.state == "AWAITING_IDENTITY" and not opening.ended
    assert clinic.writes == []
    return bot, clinic, before, opening


def turn(bot, case_id: str, number: int, text: str | None):
    caller = (
        CallerInput(turn=number, text=None, silence_ms=2000)
        if text is None
        else CallerInput(turn=number, text=text)
    )
    return bot.handle_turn(case_id, caller)


def verified(case_id: str, clinic: FakeClinicAPI | None = None):
    bot, clinic, before, opening = start(case_id, clinic)
    name_prompt = turn(bot, case_id, 1, NAME)
    assert name_prompt.state == "AWAITING_IDENTITY" and clinic.writes == []
    readback = turn(bot, case_id, 2, DOB)
    assert readback.state == "AWAITING_INTENT" and not readback.ended
    assert clinic.appointments[APPOINTMENT] == before and clinic.writes == []
    return bot, clinic, before, (opening, name_prompt, readback)


def assert_readback(action):
    for part in READBACK_PARTS:
        assert part in action.utterance, f"missing read-back component: {part}"


def assert_untouched(clinic, before):
    assert clinic.appointments[APPOINTMENT] == before
    assert clinic.writes == []


def assert_confirmed(action, clinic, before):
    after = clinic.appointments[APPOINTMENT]
    assert (action.state, action.ended, action.outcome) == ("ENDED", True, "CONFIRMED")
    assert after["status"] == "CONFIRMED"
    assert after["confirmed_at"] and after["confirmed_via"] == "callbot"
    assert clinic.writes == [(APPOINTMENT, "CONFIRMED", {})]
    for field in (
        "appointment_id",
        "patient",
        "clinic_id",
        "starts_at",
        "ends_at",
        "department",
        "attempt_count",
    ):
        assert after[field] == before[field], field
    assert after["version"] == before["version"] + 1


def assert_transfer(action, clinic, reason):
    assert (action.state, action.ended, action.outcome, action.transfer_reason) == (
        "ENDED",
        True,
        "TRANSFERRED",
        reason,
    )
    assert clinic.writes == [(APPOINTMENT, "TRANSFERRED", {"transfer_reason": reason})]
    assert clinic.appointments[APPOINTMENT]["status"] == "TRANSFERRED"


def test_TC_CF_01_standard_happy_path():
    bot, clinic, before, actions = verified("TC_CF_01")
    assert_readback(actions[-1])
    assert_confirmed(turn(bot, "TC_CF_01", 3, "Vâng, tôi đến"), clinic, before)


def test_TC_CF_02_positive_paraphrase():
    bot, clinic, before, actions = verified("TC_CF_02")
    assert_readback(actions[-1])
    assert_confirmed(turn(bot, "TC_CF_02", 3, "Được, tôi sẽ đến"), clinic, before)


def test_TC_CF_03_attendance_intent_with_final_identity_field():
    bot, clinic, before, _ = start("TC_CF_03")
    turn(bot, "TC_CF_03", 1, NAME)
    readback = turn(bot, "TC_CF_03", 2, f"Tôi sinh ngày {DOB}, tôi sẽ đến")
    assert readback.state == "AWAITING_INTENT" and not readback.ended
    assert_readback(readback)
    assert_untouched(clinic, before)
    assert_confirmed(turn(bot, "TC_CF_03", 3, "vâng"), clinic, before)


def test_TC_CF_04_identity_and_attendance_in_one_utterance():
    bot, clinic, before, _ = start("TC_CF_04")
    readback = turn(bot, "TC_CF_04", 1, f"Tôi là {NAME}, sinh ngày {DOB}, tôi sẽ đến")
    assert readback.state == "AWAITING_INTENT" and not readback.ended
    assert_readback(readback)
    assert_untouched(clinic, before)
    assert_confirmed(turn(bot, "TC_CF_04", 2, "vâng"), clinic, before)


def test_TC_CF_05_readback_has_date_time_and_clinic():
    _, clinic, before, actions = verified("TC_CF_05")
    assert_readback(actions[-1])
    assert_untouched(clinic, before)


def test_TC_CF_06_yes_during_identity_is_not_attendance_agreement():
    bot, clinic, before, _ = start("TC_CF_06")
    answer = turn(bot, "TC_CF_06", 1, "vâng")
    assert not answer.ended and answer.state == "AWAITING_IDENTITY"
    assert_untouched(clinic, before)


def test_TC_CF_07_ambiguous_after_readback():
    bot, clinic, before, _ = verified("TC_CF_07")
    answer = turn(bot, "TC_CF_07", 3, "chắc là được")
    assert not answer.ended and answer.state == "AWAITING_INTENT"
    assert_readback(answer)
    assert_untouched(clinic, before)


def test_TC_CF_08_first_failed_understanding():
    bot, clinic, before, _ = verified("TC_CF_08")
    answer = turn(bot, "TC_CF_08", 3, "bla bla")
    assert not answer.ended and answer.state == "AWAITING_INTENT"
    context = CallContext.from_dict(bot.sessions.store.get_session("TC_CF_08").context)
    assert context.failed_understandings == 1
    assert_untouched(clinic, before)


def test_TC_CF_09_two_failed_understandings_transfer():
    bot, clinic, _, _ = verified("TC_CF_09")
    first = turn(bot, "TC_CF_09", 3, "bla bla")
    assert not first.ended and clinic.writes == []
    assert_transfer(turn(bot, "TC_CF_09", 4, "xyz xyz"), clinic, "NOT_UNDERSTOOD")


def test_TC_CF_10_repeat_request_then_agreement():
    bot, clinic, before, actions = verified("TC_CF_10")
    replay = turn(bot, "TC_CF_10", 3, "gì cơ")
    assert not replay.ended and replay.state == "AWAITING_INTENT"
    assert_readback(replay)
    assert_untouched(clinic, before)
    assert_confirmed(turn(bot, "TC_CF_10", 4, "vâng"), clinic, before)


def test_TC_CF_11_explicit_decline_enters_cancel_dialogue():
    bot, clinic, before, _ = verified("TC_CF_11")
    answer = turn(bot, "TC_CF_11", 3, "Không, tôi không đến được")
    assert not answer.ended and answer.state == "AWAITING_CONFIRMATION"
    assert_untouched(clinic, before)


def test_TC_CF_12_cancel_requires_second_confirmation():
    bot, clinic, before, _ = verified("TC_CF_12")
    first = turn(bot, "TC_CF_12", 3, "Không, tôi không đến được")
    assert not first.ended
    assert_untouched(clinic, before)
    assert clinic.appointments[APPOINTMENT]["status"] not in {"CANCELLED", "CONFIRMED"}


def test_TC_CF_13_wrong_identity_cannot_confirm_or_disclose():
    bot, clinic, before, opening = start("TC_CF_13")
    prompt = turn(bot, "TC_CF_13", 1, "Trần Văn B")
    failed = prompt
    for action in (opening, failed):
        for part in READBACK_PARTS:
            assert part not in action.utterance
    assert_transfer(failed, clinic, "IDENTITY_FAILED")
    with pytest.raises(CallEnded):
        turn(bot, "TC_CF_13", 3, "Tôi sẽ đến")
    assert len(clinic.writes) == 1
    assert clinic.appointments[APPOINTMENT].get("confirmed_at") == before.get("confirmed_at")


def test_TC_CF_14_appointment_detail_request_before_identity():
    bot, clinic, before, opening = start("TC_CF_14")
    answer = turn(bot, "TC_CF_14", 1, "Lịch của tôi mấy giờ?")
    assert not answer.ended and answer.state == "AWAITING_IDENTITY"
    for action in (opening, answer):
        for part in READBACK_PARTS:
            assert part not in action.utterance
    assert_untouched(clinic, before)


def test_TC_CF_15_identity_to_confirm_boundary():
    bot, clinic, before, actions = verified("TC_CF_15")
    assert actions[1].state == "AWAITING_IDENTITY"
    assert_readback(actions[2])
    assert_untouched(clinic, before)
    assert_confirmed(turn(bot, "TC_CF_15", 3, "vâng"), clinic, before)


def test_TC_CF_16_protected_fields_after_confirmation():
    bot, clinic, before, _ = verified("TC_CF_16")
    assert_confirmed(turn(bot, "TC_CF_16", 3, "vâng"), clinic, before)


def test_TC_CF_17_other_appointment_untouched():
    clinic = FakeClinicAPI()
    other = deepcopy(clinic.appointments[APPOINTMENT])
    other["appointment_id"] = "apt_other"
    clinic.seed_appointment(other)
    bot, clinic, before, _ = verified("TC_CF_17", clinic)
    assert_confirmed(turn(bot, "TC_CF_17", 3, "vâng"), clinic, before)
    assert clinic.appointments["apt_other"] == other
    assert {write[0] for write in clinic.writes} == {APPOINTMENT}


def test_TC_CF_18_exactly_one_confirmation_side_effect():
    bot, clinic, before, _ = verified("TC_CF_18")
    assert_confirmed(turn(bot, "TC_CF_18", 3, "vâng"), clinic, before)
    assert len(clinic.writes) == 1


def test_TC_CF_19_retry_does_not_duplicate_confirmation():
    bot, clinic, before, _ = verified("TC_CF_19")
    assert_confirmed(turn(bot, "TC_CF_19", 3, "vâng"), clinic, before)
    with pytest.raises(CallEnded):
        turn(bot, "TC_CF_19", 3, "vâng")
    assert clinic.writes == [(APPOINTMENT, "CONFIRMED", {})]
    keys = [key for key, operation in clinic.requests if operation == "CONFIRMED"]
    assert len(keys) == 1 and keys[0]


def test_TC_CF_20_no_explicit_agreement_no_write():
    _, clinic, before, actions = verified("TC_CF_20")
    assert_readback(actions[-1])
    assert_untouched(clinic, before)


def test_TC_CF_21_two_silent_turns_do_not_confirm():
    bot, clinic, before, _ = verified("TC_CF_21")
    for number in (3, 4):
        answer = turn(bot, "TC_CF_21", number, None)
        assert not answer.ended and answer.state == "AWAITING_INTENT"
        assert_untouched(clinic, before)


def test_TC_CF_22_three_silent_turns_unreachable():
    bot, clinic, before, _ = verified("TC_CF_22")
    for number in (3, 4):
        assert not turn(bot, "TC_CF_22", number, None).ended
        assert_untouched(clinic, before)
    final = turn(bot, "TC_CF_22", 5, None)
    assert (final.state, final.ended, final.outcome) == ("ENDED", True, "UNREACHABLE")
    assert clinic.writes == [(APPOINTMENT, "UNREACHABLE", {"unreachable_reason": "SILENCE"})]
    assert clinic.appointments[APPOINTMENT]["status"] == "UNREACHABLE"
    assert clinic.appointments[APPOINTMENT]["attempt_count"] == before["attempt_count"] + 1


def test_TC_CF_23_off_script_request_transfers():
    bot, clinic, _, _ = verified("TC_CF_23")
    assert_transfer(turn(bot, "TC_CF_23", 3, "Có mất phí không em?"), clinic, "OUT_OF_SCOPE")


def test_TC_CF_24_clinical_question_transfers_without_advice():
    bot, clinic, _, _ = verified("TC_CF_24")
    answer = turn(bot, "TC_CF_24", 3, "Thuốc này tôi có nên uống tiếp không?")
    assert_transfer(answer, clinic, "CLINICAL_QUESTION")
    assert "nên uống" not in answer.utterance.lower()
