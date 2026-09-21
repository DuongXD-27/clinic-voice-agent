"""T-04 — hội thoại Confirm: chỉ trả CONFIRMED sau khi Clinic xác nhận ghi thành công (§1.1.3).

Orchestrator thật + FakeClinicAPI. apt_00417: 9 giờ sáng 14/10, cl_vinmec, Nội tổng quát.
"""

from typing import Any, Optional

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction import QuestionId
from callbot.engine.session import CallContext
from tests.engine.fake_clinic import FakeClinicAPI, clinic_error

SILENCE = None
FACTS = "9 giờ sáng ngày 14 tháng 10 tại Vinmec Times City"
CONFIRMED_WRITE = ("apt_00417", "CONFIRMED", {})


def _run(bot, call_id: str, lines: list[Optional[str]], start: int = 1):
    action = None
    for turn, line in enumerate(lines, start=start):
        caller = (
            CallerInput(turn=turn, text=None, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        action = bot.handle_turn(call_id, caller)
    return action


def _context(bot, call_id: str) -> CallContext:
    return CallContext.from_dict(bot.sessions.store.get_session(call_id).context)


def _at_readback(call_id: str, clinic: Optional[FakeClinicAPI] = None):
    """Outbound đã xác minh, đang chờ câu tóm tắt gộp đọc lại (Figure 0). Lượt kế tiếp là 3."""
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    summary = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"])
    assert summary.state == "AWAITING_INTENT"
    return bot, clinic, summary


def _confirm_writes(clinic: FakeClinicAPI) -> list[tuple[str, str, dict[str, Any]]]:
    return [write for write in clinic.writes if write[1] == "CONFIRMED"]


# --- Đọc lại ngày, giờ, cơ sở (§1.1.3) ------------------------------------------------


def test_summary_reads_back_date_time_and_clinic_name() -> None:
    bot, clinic, summary = _at_readback("c_t04_summary")
    assert FACTS in summary.utterance and "Nội tổng quát" in summary.utterance
    assert _context(bot, "c_t04_summary").question.question_id is QuestionId.CONFIRM_READBACK
    assert clinic.writes == []


def test_unknown_clinic_id_is_not_given_a_guessed_name() -> None:
    assert t.clinic_name({"clinic_id": "cl_unknown"}) == "Vinmec"
    assert t.clinic_name({"clinic_id": "cl_vinmec", "clinic_name": "Vinmec Central Park"}) == (
        "Vinmec Central Park"
    )


# --- Đồng ý -> ghi, rồi mới báo CONFIRMED ------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Có, tôi đến được.",
        "vâng",
        "dạ",
        "ừ",
        "vâng, cảm ơn em",
        "tôi sẽ đến",  # Bảng 1: "states or agrees they will attend"
        "xác nhận",
        "giữ nguyên lịch",
        "không hủy đâu, tôi vẫn đến",
    ],
)
def test_agreement_confirms_in_one_turn(answer: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_agree")
    action = _run(bot, "c_t04_agree", [answer], start=3)
    assert (action.ended, action.outcome, action.state) == (True, "CONFIRMED", "ENDED")
    assert clinic.writes == [CONFIRMED_WRITE]
    # Câu báo dựng từ bản ghi Mock trả về sau lệnh ghi
    assert FACTS in action.utterance
    assert bot.sessions.store.get_session("c_t04_agree").context == {}


def test_success_message_uses_the_written_record() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_record", clinic)
    confirm = clinic.confirm_appointment

    def confirm_and_report_other_clinic(*args, **kwargs):
        return {**confirm(*args, **kwargs), "clinic_id": "c_002"}

    clinic.confirm_appointment = confirm_and_report_other_clinic
    action = _run(bot, "c_t04_record", ["vâng"], start=3)
    assert action.outcome == "CONFIRMED" and "Phòng khám Đa khoa Cầu Giấy" in action.utterance


# --- Chưa rõ: đọc lại bằng câu có / không, không ghi ---------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "ờ để xem",
        "chắc là được",
        "có lẽ vậy",
        "vâng để tôi xem lại",
        "được không em?",
        "mấy giờ nhỉ?",
    ],
)
def test_unclear_answer_rereads_without_writing(answer: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_unclear")
    action = _run(bot, "c_t04_unclear", [answer], start=3)
    assert not action.ended and clinic.writes == []
    assert FACTS in action.utterance and action.utterance.endswith(t.ASK_ATTENDANCE)
    ctx = _context(bot, "c_t04_unclear")
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK and ctx.question.turn == 3
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)
    assert ctx.evidence == []


def test_yes_after_reread_confirms_with_evidence_of_that_turn(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_t04_reread")
    _run(bot, "c_t04_reread", ["chắc là được"], start=3)

    evidence = []
    confirm = bot._dialogue._gateway.confirm

    def capture(ctx):
        evidence.extend(ctx.evidence)
        return confirm(ctx)

    monkeypatch.setattr(bot._dialogue._gateway, "confirm", capture)
    action = _run(bot, "c_t04_reread", ["vâng"], start=4)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]
    assert [(e.kind, e.label, e.turn, e.question_turn) for e in evidence] == [
        ("CONFIRMATION", "AGREE", 4, 3)
    ]


def test_unclear_three_times_transfers_not_understood() -> None:
    bot, clinic, _ = _at_readback("c_t04_unclear3")
    action = _run(bot, "c_t04_unclear3", ["chắc là được", "có lẽ vậy", "để tôi xem đã"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


# --- Từ chối / đổi ý ------------------------------------------------------------------------


def test_refusal_drops_pending_and_changed_mind_needs_new_readback() -> None:
    bot, clinic, _ = _at_readback("c_t04_refuse")
    action = _run(bot, "c_t04_refuse", ["không"], start=3)
    assert action.utterance == t.ASK_CHANGE_OR_CANCEL and clinic.writes == []
    ctx = _context(bot, "c_t04_refuse")
    assert ctx.pending_action is None and ctx.evidence == []

    action = _run(bot, "c_t04_refuse", ["thôi tôi vẫn đến"], start=4)
    assert action.state == "AWAITING_CONFIRMATION" and FACTS in action.utterance
    assert clinic.writes == []

    action = _run(bot, "c_t04_refuse", ["đồng ý"], start=5)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


def test_yes_to_change_or_cancel_question_does_not_confirm() -> None:
    bot, clinic, _ = _at_readback("c_t04_open")
    action = _run(bot, "c_t04_open", ["không", "vâng"], start=3)
    assert not action.ended and clinic.writes == []


@pytest.mark.parametrize(
    "answer, state",
    [
        ("không đến được", "AWAITING_CONFIRMATION"),  # sang hủy, chờ xác nhận hủy lần hai
        ("vâng nhưng tôi muốn đổi giờ", "OFFERING_SLOTS"),
    ],
)
def test_cancel_or_reschedule_at_readback_does_not_confirm(answer: str, state: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_branch")
    action = _run(bot, "c_t04_branch", [answer], start=3)
    assert action.state == state and clinic.writes == []


# --- Ngoại lệ ở bước xác nhận ---------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, reason",
    [
        ("vâng, à mà tôi đau ngực", "CLINICAL_QUESTION"),
        ("cho tôi gặp nhân viên", "PATIENT_REQUEST"),
    ],
)
def test_exceptions_at_readback_transfer_without_confirming(answer: str, reason: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_exc")
    action = _run(bot, "c_t04_exc", [answer], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)
    assert _confirm_writes(clinic) == []


def test_silence_and_repeat_request_keep_the_readback_question() -> None:
    bot, clinic, summary = _at_readback("c_t04_silence")
    action = _run(bot, "c_t04_silence", [SILENCE], start=3)
    # T-08: nhắc rồi đọc lại nguyên văn câu tóm tắt, hỏi lại ở lượt 3
    assert action.utterance == f"{t.SILENCE} {summary.utterance}"
    question = _context(bot, "c_t04_silence").question
    assert (question.text, question.turn) == (summary.utterance, 3)

    action = _run(bot, "c_t04_silence", ["gì cơ"], start=4)
    assert action.utterance == summary.utterance
    action = _run(bot, "c_t04_silence", ["vâng"], start=5)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


# --- Kết quả ghi: chỉ CONFIRMED khi Clinic xác nhận ----------------------------------------


def test_rejected_write_is_system_error_not_confirmed() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_rejected", clinic)
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    action = _run(bot, "c_t04_rejected", ["vâng"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert "xác nhận lịch khám" not in action.utterance
    assert _confirm_writes(clinic) == []


def test_unknown_write_outcome_blocks_the_turn_instead_of_reporting() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_unknown", clinic)
    clinic.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t04_unknown", ["vâng"], start=3)
    # Mock đã ghi nhưng bot không biết: không có phản hồi CONFIRMED, không chuyển máy thay thế
    assert clinic.writes == [CONFIRMED_WRITE]


def test_version_conflict_retries_with_same_key_then_confirms() -> None:
    """§4.2.5: đọc lại, gửi lại với version mới và cùng Idempotency-Key."""
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_conflict", clinic)
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    action = _run(bot, "c_t04_conflict", ["vâng"], start=3)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]
    keys = [key for key, label in clinic.requests if label == "CONFIRMED"]
    assert keys == ["c_t04_conflict:3:confirm"] * 2


def test_write_without_confirmed_status_is_not_reported_as_confirmed() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_status", clinic)
    clinic.confirm_appointment = lambda *args, **kwargs: {
        **clinic.appointments["apt_00417"],
        "status": "SCHEDULED",
    }
    # Lệnh đã commit nên không ghi /transfer thay thế; lượt bị chặn để đối soát, không báo CONFIRMED
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t04_status", ["vâng"], start=3)
    assert clinic.writes == []


def test_resent_confirm_turn_does_not_write_twice() -> None:
    """F-03: ghi Clinic xong thì nội dung phiên bị xóa — gửi lại lượt nhận CALL_ENDED, không ghi lần hai."""
    bot, clinic, _ = _at_readback("c_t04_replay")
    assert _run(bot, "c_t04_replay", ["vâng"], start=3).outcome == "CONFIRMED"
    with pytest.raises(CallEnded):
        _run(bot, "c_t04_replay", ["vâng"], start=3)
    assert clinic.writes == [CONFIRMED_WRITE]


# --- Inbound: xác nhận lịch có sẵn là ngoài kịch bản (§1, §1.1.5) -------------------------


def _inbound_at_intent(call_id: str):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id=call_id, direction="inbound", caller_number="0912345600"))
    action = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"])
    assert action.utterance == t.ASK_INTENT_INBOUND
    return bot, clinic


def test_inbound_confirm_request_transfers_at_once_without_write() -> None:
    bot, clinic = _inbound_at_intent("c_t04_in")
    action = _run(bot, "c_t04_in", ["tôi muốn xác nhận lịch khám"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "OUT_OF_SCOPE")
    assert clinic.writes == []


def test_inbound_attendance_wording_is_not_mistaken_for_confirm() -> None:
    bot, clinic = _inbound_at_intent("c_t04_in_book")
    action = _run(bot, "c_t04_in_book", ["sáng mai tôi đến được không"], start=3)
    assert not action.ended and clinic.writes == []
