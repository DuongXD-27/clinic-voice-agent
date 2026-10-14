"""R-39: TTS lỗi giữa cuộc gọi — khách luôn nghe câu TRANSFER cố định rồi được chuyển nhân viên,
chỉ phía Clinic khác nhau theo trạng thái phiên.

Mỗi test là một dòng của bảng 2.2 trong docs/plans/call-lifecycle-recovery-plan-2026-10-11.md.
"""

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t
from callbot.engine.policy import output_guard
from clinic_mock_sim import FakeClinicAPI, clinic_error

CALL_ID = "c_tts_error"
APPOINTMENT = "apt_00417"
BEFORE_CANCEL = ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch", "Vâng"]
CANCEL_TURN = (5, "Hủy giúp tôi")


@pytest.fixture
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def bot(clinic, store):
    bot = create_orchestrator(clinic, store=store)
    bot.start_call(CallStart(call_id=CALL_ID, direction="outbound", appointment_id=APPOINTMENT))
    return bot


def _say(bot, turn: int, text: str):
    return bot.handle_turn(CALL_ID, CallerInput(turn=turn, text=text))


def _transfers(clinic) -> list:
    return [write for write in clinic.writes if write[1] == "TRANSFERRED"]


def test_mid_conversation_transfers_system_error_once(bot, clinic, store) -> None:
    assert not _say(bot, 1, BEFORE_CANCEL[0]).ended

    recovery = bot.handle_tts_error(CALL_ID)

    assert recovery.utterance == t.TRANSFER
    assert recovery.action is not None
    assert (recovery.action.outcome, recovery.action.transfer_reason) == (
        "TRANSFERRED",
        "SYSTEM_ERROR",
    )
    assert recovery.action.utterance == t.TRANSFER
    assert (recovery.preserve_business_outcome, recovery.reconciliation_required) == (False, False)
    assert _transfers(clinic) == [(APPOINTMENT, "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]
    session = store.get_session(CALL_ID)
    assert session.ended and session.last_completed_turn == 2  # lượt điều khiển là lượt kế tiếp


def test_a_second_error_in_the_same_call_writes_nothing_more(bot, clinic) -> None:
    """Dòng "đã kết thúc bằng chuyển máy": phiên ENDED thì không chạy lượt, không ghi."""
    bot.handle_tts_error(CALL_ID)
    requests = list(clinic.requests)

    again = bot.handle_tts_error(CALL_ID)

    assert again.utterance == t.TRANSFER and again.action is None
    assert again.preserve_business_outcome is True
    assert clinic.requests == requests
    assert len(_transfers(clinic)) == 1


def test_inbound_without_appointment_writes_nothing(clinic, store) -> None:
    bot = create_orchestrator(clinic, store=store)
    bot.start_call(CallStart(call_id=CALL_ID, direction="inbound", caller_number="0912345600"))
    appointments = len(clinic.appointments)

    recovery = bot.handle_tts_error(CALL_ID)

    assert recovery.utterance == t.TRANSFER
    assert recovery.action is not None and recovery.action.outcome == "TRANSFERRED"
    assert recovery.preserve_business_outcome is False
    assert clinic.writes == [] and clinic.requests == []
    assert len(clinic.appointments) == appointments  # không tạo lịch


def test_after_a_successful_write_the_result_is_kept(bot, clinic) -> None:
    for turn, text in enumerate(BEFORE_CANCEL, 1):
        _say(bot, turn, text)
    assert _say(bot, *CANCEL_TURN).outcome == "CANCELLED"  # TTS lỗi ở chính câu báo kết quả
    requests = list(clinic.requests)

    recovery = bot.handle_tts_error(CALL_ID)

    assert recovery.utterance == t.TRANSFER and recovery.action is None
    assert (recovery.preserve_business_outcome, recovery.reconciliation_required) == (True, False)
    assert clinic.requests == requests and _transfers(clinic) == []


def test_unknown_write_waits_for_reconciliation(monkeypatch, bot, clinic) -> None:
    for turn, text in enumerate(BEFORE_CANCEL, 1):
        _say(bot, turn, text)

    def timeout(*_args, **_kwargs):
        raise clinic_error(None, "TIMEOUT", outcome_known=False)

    monkeypatch.setattr(clinic, "cancel_appointment", timeout)
    with pytest.raises(ReconciliationRequired):
        _say(bot, *CANCEL_TURN)
    requests = list(clinic.requests)

    recovery = bot.handle_tts_error(CALL_ID)

    assert recovery.utterance == t.TRANSFER and recovery.action is None
    assert (recovery.preserve_business_outcome, recovery.reconciliation_required) == (False, True)
    assert clinic.requests == requests and _transfers(clinic) == []


def test_after_hangup_nothing_is_written(bot, clinic) -> None:
    assert not _say(bot, 1, BEFORE_CANCEL[0]).ended
    requests = list(clinic.requests)
    bot.request_call_close(CALL_ID)

    with pytest.raises(CallEnded):
        bot.handle_tts_error(CALL_ID)
    assert clinic.requests == requests


def test_transfer_write_rejected_still_hands_off(bot, clinic) -> None:
    """Clinic từ chối /transfer (lỗi rõ ràng): vẫn chuyển nhân viên, không ghi lại lần hai."""
    assert not _say(bot, 1, BEFORE_CANCEL[0]).ended
    clinic.fail_next("transfer_appointment", clinic_error(422, "INVALID_TRANSITION"))

    recovery = bot.handle_tts_error(CALL_ID)

    assert recovery.action is not None and recovery.action.outcome == "TRANSFERRED"
    assert _transfers(clinic) == []
    assert bot.handle_tts_error(CALL_ID).action is None


def test_control_turn_carries_no_caller_speech() -> None:
    """Lượt điều khiển không phải lời khách: không text, không im lặng (không tính vào luật im lặng),
    và khác đầu vào của lượt thường cùng số lượt (gửi lại không bị nhận nhầm)."""
    control = CallerInput(turn=2, control_event="TTS_ERROR")

    assert (control.is_silence, control.transcript) == (False, "")
    assert control.fingerprint() == {
        "text": None,
        "silence_ms": 0,
        "audio_url": None,
        "control_event": "TTS_ERROR",
    }
    assert control.fingerprint() != CallerInput(turn=2, text=None).fingerprint()


def test_fallback_guard_allows_only_the_fixed_transfer_sentence() -> None:
    assert output_guard.check_tts_fallback(t.TRANSFER).ok
    assert not output_guard.check_tts_fallback(t.GREETING_OUTBOUND).ok
    assert not output_guard.check_tts_fallback(t.TRANSFER + " ").ok


def test_control_event_cannot_carry_caller_input() -> None:
    with pytest.raises(ValueError):
        CallerInput(turn=1, text="alo", control_event="TTS_ERROR")
    with pytest.raises(ValueError):
        CallerInput(turn=1, silence_ms=500, control_event="ASR_ERROR")
