"""Simulated phone events use the real core, Redis session and Clinic Gateway."""

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    PhoneStatus,
    ReconciliationRequired,
    TurnOutOfOrder,
    create_orchestrator,
)
from callbot.engine.tools.clinic_gateway import WRITE_MAX_SENDS
from callbot.transports.phone import PhoneStatusAdapter
from clinic_mock_sim import clinic_error


def _adapter(clinic, direction="outbound"):
    bot = create_orchestrator(clinic)
    bot.start_call(
        CallStart(
            call_id="c_phone_status",
            direction=direction,
            appointment_id="apt_00417" if direction == "outbound" else None,
            caller_number="0912345600" if direction == "inbound" else None,
        )
    )
    return bot, PhoneStatusAdapter(bot)


@pytest.mark.parametrize("status", list(PhoneStatus))
def test_simulated_dial_result_marks_once_through_core(clinic, status):
    _, adapter = _adapter(clinic)
    action = adapter.handle_status("c_phone_status", turn=1, status=status)
    assert (action.state, action.ended, action.outcome) == ("ENDED", True, "UNREACHABLE")
    assert action.unreachable_reason == status.value
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": status.value})]
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1
    for turn in (1, 2):
        with pytest.raises(CallEnded):
            adapter.handle_status("c_phone_status", turn=turn, status=status)
    assert len(clinic.writes) == 1
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


@pytest.mark.parametrize("status", list(PhoneStatus))
def test_inbound_dial_result_transfers_without_write(clinic, status):
    _, adapter = _adapter(clinic, "inbound")
    action = adapter.handle_status("c_phone_status", turn=1, status=status)
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "SYSTEM_ERROR"
    assert clinic.writes == []


def test_status_obeys_turn_order_and_cannot_overwrite_completed_call(clinic):
    bot, adapter = _adapter(clinic)
    with pytest.raises(TurnOutOfOrder):
        adapter.handle_status("c_phone_status", turn=2, status=PhoneStatus.LINE_BUSY)
    assert clinic.writes == []
    bot.handle_turn("c_phone_status", CallerInput(turn=1, text="cho tôi gặp nhân viên"))
    with pytest.raises(CallEnded):
        adapter.handle_status("c_phone_status", turn=2, status=PhoneStatus.NO_ANSWER)
    assert len(clinic.writes) == 1 and clinic.writes[0][1] == "TRANSFERRED"
    assert clinic.appointments["apt_00417"]["attempt_count"] == 0


@pytest.mark.parametrize("status", list(PhoneStatus))
def test_status_version_conflict_retries_same_key(clinic, status):
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    _, adapter = _adapter(clinic)
    action = adapter.handle_status("c_phone_status", turn=1, status=status)
    assert action.outcome == "UNREACHABLE"
    keys = [key for key, op in clinic.requests if op == "unreachable"]
    assert keys == ["c_phone_status:1:unreachable"] * 2
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


def test_unknown_status_write_blocks_retry_without_new_write(clinic):
    clinic.fail_unknown("mark_unreachable", WRITE_MAX_SENDS, apply_first=True)
    _, adapter = _adapter(clinic)
    for _ in range(2):
        with pytest.raises(ReconciliationRequired):
            adapter.handle_status("c_phone_status", turn=1, status=PhoneStatus.NO_ANSWER)
    assert len(clinic.writes) == 1
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


def test_status_does_not_run_speech_extraction(clinic, monkeypatch):
    bot, adapter = _adapter(clinic)

    def forbidden(*args, **kwargs):
        pytest.fail("phone status must bypass speech extraction")

    monkeypatch.setattr(bot._extractor, "extract", forbidden)
    assert (
        adapter.handle_status("c_phone_status", turn=1, status=PhoneStatus.NO_ANSWER).outcome
        == "UNREACHABLE"
    )


def test_rejected_status_write_does_not_claim_unreachable(clinic):
    clinic.fail_next("mark_unreachable", clinic_error(409, "INVALID_STATE_TRANSITION"))
    _, adapter = _adapter(clinic)
    action = adapter.handle_status("c_phone_status", turn=1, status=PhoneStatus.LINE_BUSY)
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "SYSTEM_ERROR"
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]
    assert clinic.appointments["apt_00417"]["attempt_count"] == 0


@pytest.mark.parametrize(
    "extra",
    [{"text": "busy"}, {"audio_url": "https://clip"}, {"silence_ms": 1}, {"asr_confidence": 1}],
)
def test_status_cannot_be_mixed_with_speech(extra):
    with pytest.raises(ValueError):
        CallerInput(turn=1, phone_status=PhoneStatus.LINE_BUSY, **extra)


def test_status_is_typed_and_part_of_request_fingerprint():
    with pytest.raises(ValueError):
        CallerInput(turn=1, phone_status="LINE_BUSY")
    with pytest.raises(ValueError):
        CallerInput(turn=0, phone_status=PhoneStatus.LINE_BUSY)
    busy = CallerInput(turn=1, phone_status=PhoneStatus.LINE_BUSY)
    no_answer = CallerInput(turn=1, phone_status=PhoneStatus.NO_ANSWER)
    assert busy.fingerprint() != no_answer.fingerprint()
    assert busy.fingerprint() != CallerInput(turn=1, text="").fingerprint()
