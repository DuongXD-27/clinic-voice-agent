"""T-08 — Silence và tín hiệu đường dây: outcome và thao tác Mock đúng theo hướng gọi (§1.1.7, §4.2.5).

Orchestrator thật + FakeClinicAPI. apt_00417: 9 giờ sáng 14/10, cl_vinmec, Nội tổng quát; bệnh nhân
Nguyễn Văn A, 14/03/1978, số 0912345600.
"""

from typing import Optional

import pytest

from callbot.engine import CallerInput, CallStart, ReconciliationRequired, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction import QuestionId
from callbot.engine.session import CallContext
from clinic_mock_sim import FakeClinicAPI, clinic_error

SILENCE = None
NAME, DOB = "Nguyễn Văn A", "14/03/1978"
UNREACHABLE_SILENCE = ("apt_00417", "UNREACHABLE", {"unreachable_reason": "SILENCE"})
UNREACHABLE_VOICEMAIL = ("apt_00417", "UNREACHABLE", {"unreachable_reason": "VOICEMAIL"})
# Chi tiết lịch không được nghe trên hộp thư (§1.1.7)
APPOINTMENT_FACTS = ("14 tháng 10", "9 giờ", "Nội tổng quát", "Times City")

# Lời người gọi để tới từng câu hỏi, và câu hỏi đang chờ sau các lượt đó
OUTBOUND_STEPS = {
    QuestionId.ASK_NAME: [],
    QuestionId.ASK_DOB: [NAME],
    QuestionId.CONFIRM_READBACK: [NAME, DOB],
    QuestionId.ASK_INTENT: [NAME, DOB, "không"],
    QuestionId.OFFER_SLOTS: [NAME, DOB, "tôi muốn đổi lịch"],
    QuestionId.SLOT_READBACK: [NAME, DOB, "tôi muốn đổi lịch", "khung 1"],
    QuestionId.CANCEL_RECONFIRM: [NAME, DOB, "tôi muốn hủy lịch"],
}
INBOUND_STEPS = {
    QuestionId.ASK_NAME: [],
    QuestionId.ASK_DOB: [NAME],
    QuestionId.ASK_INTENT: [NAME, DOB],
    QuestionId.OFFER_SLOTS: [NAME, DOB, "tôi muốn đặt lịch khám"],
    QuestionId.SLOT_READBACK: [NAME, DOB, "tôi muốn đặt lịch khám", "khung 1"],
}


def _start(call_id: str, direction: str, clinic: Optional[FakeClinicAPI] = None):
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    if direction == "outbound":
        call = CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")
    else:
        call = CallStart(call_id=call_id, direction="inbound", caller_number="0912345600")
    opening = bot.start_call(call)
    return bot, clinic, [opening]


def _run(bot, call_id: str, lines: list[Optional[str]], actions: list, start: int):
    for turn, line in enumerate(lines, start=start):
        caller = (
            CallerInput(turn=turn, text=None, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        actions.append(bot.handle_turn(call_id, caller))
    return actions[-1]


def _call(call_id: str, direction: str, lines: list[Optional[str]], clinic=None):
    bot, clinic, actions = _start(call_id, direction, clinic)
    _run(bot, call_id, lines, actions, start=1)
    return bot, clinic, actions


def _question(bot, call_id: str) -> QuestionId:
    ctx = CallContext.from_dict(bot.sessions.store.get_session(call_id).context)
    return ctx.question.question_id


def _ended(action, outcome: str, reason: str) -> None:
    assert action.ended and action.outcome == outcome
    assert (action.transfer_reason or action.unreachable_reason) == reason


# --- Ngưỡng 3 lượt im lặng theo hướng gọi, ở mọi bước ----------------------------------------


@pytest.mark.parametrize("question", list(OUTBOUND_STEPS), ids=lambda q: q.value)
def test_outbound_three_silences_end_unreachable_at_every_step(question: QuestionId) -> None:
    call_id = f"c_t08_out_{question.value}"
    bot, clinic, actions = _call(call_id, "outbound", OUTBOUND_STEPS[question])
    assert _question(bot, call_id) is question
    _run(bot, call_id, [SILENCE, SILENCE, SILENCE], actions, start=len(actions))
    _ended(actions[-1], "UNREACHABLE", "SILENCE")
    assert actions[-1].utterance == t.GOODBYE_UNREACHABLE
    assert clinic.writes == [UNREACHABLE_SILENCE]
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


@pytest.mark.parametrize("question", list(INBOUND_STEPS), ids=lambda q: q.value)
def test_inbound_three_silences_transfer_without_write_at_every_step(question: QuestionId) -> None:
    call_id = f"c_t08_in_{question.value}"
    bot, clinic, actions = _call(call_id, "inbound", INBOUND_STEPS[question])
    assert _question(bot, call_id) is question
    _run(bot, call_id, [SILENCE, SILENCE, SILENCE], actions, start=len(actions))
    _ended(actions[-1], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert (
        clinic.writes == []
    )  # §2.1: inbound chưa đặt lịch không có lệnh ghi, không bao giờ /unreachable


# --- Đếm im lặng riêng với không hiểu ----------------------------------------------------------


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
def test_speech_resets_silence_counter(direction: str) -> None:
    _, clinic, actions = _call(
        f"c_t08_reset_{direction}", direction, [SILENCE, SILENCE, NAME, SILENCE, SILENCE]
    )
    assert not actions[-1].ended and clinic.writes == []


def test_repeat_request_resets_silence_counter() -> None:
    _, clinic, actions = _call("c_t08_repeat", "outbound", [SILENCE, SILENCE, "gì cơ", SILENCE])
    assert not actions[-1].ended and clinic.writes == []


def test_silence_is_never_a_failed_understanding() -> None:
    # Im lặng xen giữa không đẩy bộ đếm §1.1.5: lượt không hiểu thứ hai mới chuyển
    _, _, actions = _call("c_t08_mixed", "outbound", [NAME, SILENCE, "ờ để xem", SILENCE])
    assert not actions[-1].ended
    _, _, actions = _call(
        "c_t08_mixed2", "outbound", [NAME, SILENCE, "ờ để xem", SILENCE, "ờ để xem"]
    )
    _ended(actions[-1], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_failed_understandings_do_not_count_towards_silence() -> None:
    # Lượt nói (dù không hiểu) cắt chuỗi im lặng
    _, clinic, actions = _call("c_t08_cut", "outbound", [SILENCE, SILENCE, "ờ", SILENCE, SILENCE])
    assert not actions[-1].ended and clinic.writes == []


# --- Nhắc im lặng: hỏi lại câu đang chờ; xác nhận chỉ cho câu vừa nghe -------------------------


@pytest.mark.parametrize("question", list(OUTBOUND_STEPS), ids=lambda q: q.value)
def test_silence_prompt_repeats_the_pending_question(question: QuestionId) -> None:
    call_id = f"c_t08_prompt_{question.value}"
    bot, _, actions = _call(call_id, "outbound", OUTBOUND_STEPS[question])
    prompt = _run(bot, call_id, [SILENCE], actions, start=len(actions))
    assert prompt.utterance.startswith(t.SILENCE)
    assert prompt.state == actions[-2].state and _question(bot, call_id) is question
    ctx = CallContext.from_dict(bot.sessions.store.get_session(call_id).context)
    assert prompt.utterance == f"{t.SILENCE} {ctx.question.text}"
    assert ctx.question.turn == len(actions) - 1  # hỏi lại ở lượt nhắc (actions[0] là lượt 0)


@pytest.mark.parametrize(
    "question, answer, outcome",
    [
        (QuestionId.CONFIRM_READBACK, "vâng", "CONFIRMED"),
        (QuestionId.SLOT_READBACK, "đúng rồi", "RESCHEDULED"),
        (QuestionId.CANCEL_RECONFIRM, "đúng rồi, hủy giúp tôi", "CANCELLED"),
    ],
    ids=lambda v: v.value if isinstance(v, QuestionId) else v,
)
def test_write_after_silence_only_answers_the_repeated_question(
    question: QuestionId, answer: str, outcome: str
) -> None:
    """G-1: trước T-08 câu nhắc chỉ là "còn nghe máy không" mà "vâng" vẫn mở khóa lệnh ghi.

    Nay câu ngay trước lượt ghi luôn chứa nguyên văn câu hỏi xác nhận.
    """
    call_id = f"c_t08_g1_{question.value}"
    bot, clinic, actions = _call(call_id, "outbound", OUTBOUND_STEPS[question])
    confirmation = CallContext.from_dict(bot.sessions.store.get_session(call_id).context).question
    _run(bot, call_id, [SILENCE, SILENCE, answer], actions, start=len(actions))
    assert actions[-1].outcome == outcome
    assert confirmation.text in actions[-2].utterance
    assert len(clinic.writes) == 1 and clinic.writes[0][1] == outcome


@pytest.mark.parametrize(
    "question, answer, outcome",
    [
        (QuestionId.CONFIRM_READBACK, "vâng", "CONFIRMED"),
        (QuestionId.SLOT_READBACK, "đúng rồi", "RESCHEDULED"),
        (QuestionId.CANCEL_RECONFIRM, "đúng rồi, hủy giúp tôi", "CANCELLED"),
    ],
    ids=lambda v: v.value if isinstance(v, QuestionId) else v,
)
def test_agree_after_not_understood_prompt_asks_again_instead_of_writing(
    question: QuestionId, answer: str, outcome: str
) -> None:
    """ "Em chưa hiểu, nói lại giúp em" không nhắc câu hỏi: "vâng" sau đó là chưa rõ -> hỏi lại câu
    xác nhận, không ghi và không rơi vào guardrail thành SYSTEM_ERROR. Đồng ý câu hỏi lại mới ghi."""
    call_id = f"c_t08_nu_{question.value}"
    bot, clinic, actions = _call(call_id, "outbound", OUTBOUND_STEPS[question])
    _run(bot, call_id, ["bla bla", answer], actions, start=len(actions))
    assert actions[-2].utterance == t.NOT_UNDERSTOOD
    assert not actions[-1].ended and clinic.writes == []
    assert _question(bot, call_id) is question
    _run(bot, call_id, [answer], actions, start=len(actions))
    assert actions[-1].outcome == outcome
    assert len(clinic.writes) == 1 and clinic.writes[0][1] == outcome


# --- Voicemail (outbound) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "lines",
    [
        ["Xin vui lòng để lại lời nhắn sau tiếng bíp"],
        [NAME, "Xin để lại lời nhắn sau tiếng bíp"],
        [SILENCE, SILENCE, "vui lòng để lại lời nhắn"],
        ["Xin chào, bạn đã gọi đến số của Lan. Hiện không thể nghe máy"],
        ["Hi, you've reached Lan, I can't take your call right now"],
    ],
    ids=["turn1", "after_name", "after_two_silences", "personal_vi", "personal_en"],
)
def test_voicemail_ends_unreachable_without_disclosing(lines: list[Optional[str]]) -> None:
    _, clinic, actions = _call(
        f"c_t08_vm_{len(lines)}_{hash(tuple(map(str, lines)))}", "outbound", lines
    )
    _ended(actions[-1], "UNREACHABLE", "VOICEMAIL")
    assert clinic.writes == [UNREACHABLE_VOICEMAIL]
    spoken = " ".join(action.utterance for action in actions)
    assert not any(fact in spoken for fact in APPOINTMENT_FACTS)


def test_three_silences_on_voicemail_never_disclose() -> None:
    _, _, actions = _call("c_t08_silent_vm", "outbound", [SILENCE, SILENCE, SILENCE])
    spoken = " ".join(action.utterance for action in actions)
    assert not any(fact in spoken for fact in APPOINTMENT_FACTS)


def test_inbound_voicemail_wording_is_not_unreachable() -> None:
    # §1.1.7 chỉ áp dụng outbound; inbound nghe câu hộp thư như câu không hiểu
    _, clinic, actions = _call(
        "c_t08_in_vm", "inbound", ["để lại lời nhắn sau tiếng bíp", "để lại lời nhắn sau tiếng bíp"]
    )
    _ended(actions[-1], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == []


def test_human_who_is_busy_is_not_voicemail() -> None:
    _, clinic, actions = _call(
        "c_t08_busy_human",
        "outbound",
        ["tôi đang lái xe không nghe máy được, lát gọi lại sau giúp tôi"],
    )
    assert not actions[-1].ended and clinic.writes == []


# --- Kết quả ghi /unreachable -------------------------------------------------------------------


@pytest.mark.parametrize(
    "failures",
    [
        [clinic_error(409, "INVALID_STATE_TRANSITION")],
        [clinic_error(409, "VERSION_CONFLICT"), clinic_error(409, "VERSION_CONFLICT")],
        [clinic_error(422, "IDEMPOTENCY_CONFLICT")],
    ],
    ids=["invalid_state", "version_conflict_twice", "idempotency_conflict"],
)
def test_rejected_unreachable_is_never_reported(failures) -> None:
    """Không báo UNREACHABLE: chuyển máy SYSTEM_ERROR và ghi /transfer để nhân viên xử lý."""
    clinic = FakeClinicAPI()
    for failure in failures:
        clinic.fail_next("mark_unreachable", failure)
    _, clinic, actions = _call("c_t08_rejected", "outbound", [SILENCE, SILENCE, SILENCE], clinic)
    _ended(actions[-1], "TRANSFERRED", "SYSTEM_ERROR")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]


def test_version_conflict_once_retries_same_key_and_marks_once() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    _, clinic, actions = _call("c_t08_conflict", "outbound", [SILENCE, SILENCE, SILENCE], clinic)
    _ended(actions[-1], "UNREACHABLE", "SILENCE")
    assert clinic.writes == [UNREACHABLE_SILENCE]
    keys = [key for key, op in clinic.requests if op == "unreachable"]
    assert keys == ["c_t08_conflict:3:unreachable"] * len(keys) and len(keys) == 2
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


def test_unknown_unreachable_outcome_blocks_for_reconciliation() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("mark_unreachable", outcome_unknown=True, apply_first=True)
    bot, clinic, actions = _start("c_t08_unknown", "outbound", clinic)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t08_unknown", [SILENCE, SILENCE, SILENCE], actions, start=1)
