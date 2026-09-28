"""T-05 — hội thoại Cancel: hai lượt tách bạch, lý do đúng, chỉ CANCELLED sau khi Clinic xác nhận ghi.

Orchestrator thật + FakeClinicAPI + fakeredis. apt_00417: 9 giờ sáng 14/10, cl_vinmec, Nội tổng quát.
Bảng AC ở `docs/plans/t05-cancel-dialogue.md` §6 và §8.6; mỗi nhóm dưới đây ghi rõ AC tương ứng.
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
from callbot.engine.extraction import Intent, QuestionId
from callbot.engine.extraction.semantic import (
    LLMSemanticExtractor,
    ReplyKind,
    SemanticContext,
    SemanticOutcome,
)
from callbot.engine.session import CallContext
from callbot.engine.tools.clinic_gateway import WRITE_MAX_SENDS
from clinic_mock_sim import FakeClinicAPI, clinic_error
from inference.llm.providers.base import StructuredReply

SILENCE = None
FACTS = "9 giờ sáng ngày 14 tháng 10 tại Vinmec Times City"


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


def _verified(call_id: str, clinic: Optional[FakeClinicAPI] = None):
    """Outbound đã xác minh, đang ở câu tóm tắt gộp (Figure 0). Lượt kế tiếp là 3."""
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    summary = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"])
    assert summary.state == "AWAITING_INTENT"
    return bot, clinic, summary


def _requesting(call_id: str, request: str = "Tôi muốn hủy lịch", clinic=None):
    """Đã nêu yêu cầu hủy ở lượt 3 và đang chờ xác nhận lần hai. Lượt kế tiếp là 4."""
    bot, clinic, _ = _verified(call_id, clinic)
    action = _run(bot, call_id, [request], start=3)
    assert action.state == "AWAITING_CONFIRMATION" and action.utterance == t.CANCEL_RECONFIRM
    assert clinic.writes == []
    return bot, clinic


def _cancel_writes(clinic: FakeClinicAPI) -> list[tuple[str, str, dict[str, Any]]]:
    return [write for write in clinic.writes if write[1] == "CANCELLED"]


def _cancelled(appointment_id: str, reason: str) -> tuple[str, str, dict[str, Any]]:
    return (appointment_id, "CANCELLED", {"cancel_reason": reason})


def _capture_cancel(monkeypatch, bot) -> list[tuple[Any, ...]]:
    """Bằng chứng + lý do tại đúng thời điểm gọi Gateway — F-03 xóa context ngay sau ghi thành công."""
    captured: list[tuple[Any, ...]] = []
    cancel = bot._dialogue._gateway.cancel

    def capture(ctx: CallContext, reason: str):
        captured.append((reason, ctx.cancel_reason, [(e.kind, e.turn) for e in ctx.evidence]))
        return cancel(ctx, reason)

    monkeypatch.setattr(bot._dialogue._gateway, "cancel", capture)
    return captured


# --- AC-1: yêu cầu và xác nhận phải ở hai lượt khác nhau -------------------------------------


def test_request_turn_asks_for_a_second_confirmation_without_writing() -> None:
    bot, clinic = _requesting("c_t05_request")
    ctx = _context(bot, "c_t05_request")
    assert ctx.question.question_id is QuestionId.CANCEL_RECONFIRM and ctx.question.turn == 3
    assert [(e.kind, e.turn) for e in ctx.evidence] == [("REQUEST", 3)]
    assert clinic.writes == []


def test_request_and_confirmation_in_one_sentence_is_still_only_a_request() -> None:
    """ "Tôi muốn hủy, xác nhận hủy luôn" ở lượt yêu cầu đầu vẫn chỉ là REQUEST (SF-05)."""
    bot, clinic = _requesting("c_t05_one_turn", "Tôi muốn hủy lịch, xác nhận hủy luôn")
    assert clinic.writes == []
    assert [e.kind for e in _context(bot, "c_t05_one_turn").evidence] == ["REQUEST"]


def test_second_turn_with_an_explicit_cancel_verb_writes_with_both_evidences(monkeypatch) -> None:
    bot, clinic = _requesting("c_t05_two_turns")
    captured = _capture_cancel(monkeypatch, bot)
    action = _run(bot, "c_t05_two_turns", ["Hủy giúp tôi"], start=4)

    assert (action.ended, action.outcome, action.state) == (True, "CANCELLED", "ENDED")
    assert action.utterance == t.cancelled_done()
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]
    assert captured == [("UNSPECIFIED", None, [("REQUEST", 3), ("CONFIRMATION", 4)])]
    assert bot.sessions.store.get_session("c_t05_two_turns").context == {}


# --- AC-2: ngưỡng AGREE của câu hủy không được nới ---------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "vâng",
        "dạ",
        "ừ",
        "có",
        "được",
        "đúng",
        "ok",
        "chắc là hủy",  # ngập ngừng
        "thôi hủy đi",  # mâu thuẫn
        "dung huy",  # không dấu: "đúng, hủy" hay "đừng hủy"
    ],
)
def test_answers_below_the_cancel_threshold_never_write(answer: str) -> None:
    bot, clinic = _requesting("c_t05_threshold")
    action = _run(bot, "c_t05_threshold", [answer], start=4)
    assert not action.ended and clinic.writes == []
    ctx = _context(bot, "c_t05_threshold")
    assert [e.kind for e in ctx.evidence] == ["REQUEST"]
    assert ctx.question.question_id is QuestionId.CANCEL_RECONFIRM


@pytest.mark.parametrize("answer", ["Không, hủy đi", "Đừng. Hủy đi.", "khong, huy di"])
def test_contradictory_cancel_answer_is_asked_again_without_writing(answer: str) -> None:
    """AC-2: "không, hủy đi" là hai mệnh đề ngược nhau, không phải "đừng hủy".

    Trước tầng ngữ nghĩa, `clean` bỏ dấu phẩy nên câu này khớp nguyên cụm "không hủy" và bot tự
    chọn giữ lịch — chọn hộ người gọi ở một câu mâu thuẫn. Nay hỏi lại (plan T-05 §8.1, ca 2).
    """
    bot, clinic = _requesting("c_t05_contradiction")
    action = _run(bot, "c_t05_contradiction", [answer], start=4)

    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []
    ctx = _context(bot, "c_t05_contradiction")
    assert ctx.pending_action == "CANCEL"  # không bỏ hủy, cũng không ghi hủy
    assert [e.kind for e in ctx.evidence] == ["REQUEST"]


def test_an_uninterrupted_refusal_still_keeps_the_appointment() -> None:
    """Đối chứng của ca trên: "không hủy đi" liền mạch vẫn là lời giữ lịch."""
    bot, clinic = _requesting("c_t05_uninterrupted")
    action = _run(bot, "c_t05_uninterrupted", ["Không hủy đi"], start=4)
    assert action.state == "AWAITING_INTENT" and FACTS in action.utterance
    assert clinic.writes == []
    assert _context(bot, "c_t05_uninterrupted").pending_action is None


def test_polite_answer_is_asked_again_with_the_choice_question() -> None:
    bot, clinic = _requesting("c_t05_polite")
    action = _run(bot, "c_t05_polite", ["Vâng"], start=4)
    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []
    # Câu lựa chọn nói rõ cụm cần nói, và lượt sau nói đúng cụm đó thì mới hủy
    assert "hủy lịch" in t.CANCEL_CHOICE
    action = _run(bot, "c_t05_polite", ["Hủy lịch"], start=5)
    assert action.outcome == "CANCELLED" and clinic.writes == [
        _cancelled("apt_00417", "UNSPECIFIED")
    ]


# --- AC-3, AC-4: vòng đời lý do hủy -------------------------------------------------------------


@pytest.mark.parametrize(
    "request_line, reason",
    [
        ("Tôi muốn hủy lịch vì hôm đó tôi bận", "PATIENT_UNAVAILABLE"),
        ("Tôi muốn hủy, tôi khỏi rồi", "NO_LONGER_NEEDED"),
        ("Tôi muốn hủy, tôi khám chỗ khác rồi", "WENT_ELSEWHERE"),
        ("Tôi muốn hủy lịch, đắt quá", "COST"),
        ("Tôi muốn hủy lịch", "UNSPECIFIED"),
        ("Tôi muốn hủy, vợ tôi bảo thế", "UNSPECIFIED"),  # không suy diễn lý do
    ],
)
def test_reason_from_the_request_turn_is_written(request_line: str, reason: str) -> None:
    bot, clinic = _requesting("c_t05_reason", request_line)
    action = _run(bot, "c_t05_reason", ["Hủy giúp tôi"], start=4)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", reason)]


def test_reason_given_on_a_middle_turn_is_kept_and_the_cancel_question_is_repeated() -> None:
    """G-1: lượt chỉ nêu lý do phải giữ được lý do và hỏi lại chính câu xác nhận hủy."""
    bot, clinic = _requesting("c_t05_middle", "Tôi muốn hủy lịch")
    action = _run(bot, "c_t05_middle", ["Hôm đó tôi đi công tác"], start=4)

    assert action.utterance == t.CANCEL_REASON_NOTED and clinic.writes == []
    ctx = _context(bot, "c_t05_middle")
    assert ctx.cancel_reason == "PATIENT_UNAVAILABLE"
    # Hiểu được lý do là tiến triển: không tính vào bộ đếm không hiểu §1.1.5
    assert (ctx.unclear_streak, ctx.failed_understandings) == (0, 0)
    # Câu hỏi được hỏi lại ở lượt 4 -> "hủy giúp tôi" ở lượt 5 trả lời đúng câu ngay trước
    assert ctx.question.question_id is QuestionId.CANCEL_RECONFIRM and ctx.question.turn == 4

    action = _run(bot, "c_t05_middle", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "PATIENT_UNAVAILABLE")]


def test_reason_on_the_confirmation_turn_is_written() -> None:
    bot, clinic = _requesting("c_t05_reason_last")
    action = _run(bot, "c_t05_reason_last", ["Hủy giúp tôi, đắt quá"], start=4)
    assert action.outcome == "CANCELLED" and clinic.writes == [_cancelled("apt_00417", "COST")]


def test_a_new_explicit_reason_replaces_the_previous_one() -> None:
    """G-2 / AC-4: bận -> chi phí cao thì ghi COST, không giữ lý do đầu."""
    bot, clinic = _requesting("c_t05_update", "Tôi muốn hủy lịch vì bận")
    action = _run(bot, "c_t05_update", ["Hủy giúp tôi vì chi phí cao"], start=4)
    assert action.outcome == "CANCELLED" and clinic.writes == [_cancelled("apt_00417", "COST")]


def test_a_turn_without_a_reason_keeps_the_reason_already_recorded() -> None:
    bot, clinic = _requesting("c_t05_keep", "Tôi muốn hủy lịch vì bận")
    _run(bot, "c_t05_keep", ["Vâng"], start=4)
    assert _context(bot, "c_t05_keep").cancel_reason == "PATIENT_UNAVAILABLE"
    action = _run(bot, "c_t05_keep", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "PATIENT_UNAVAILABLE")]


def test_conflicting_reasons_clear_the_previous_one_instead_of_keeping_it() -> None:
    """AC-3: nhiều lý do trong một câu -> UNSPECIFIED; không âm thầm giữ lý do cũ (§3.2.3)."""
    bot, clinic = _requesting("c_t05_conflict_reason", "Tôi muốn hủy lịch vì bận")
    action = _run(bot, "c_t05_conflict_reason", ["Bận mà cũng đắt quá"], start=4)
    # Chưa xác định được lý do nào: không đọc câu "đã ghi nhận lý do"
    assert action.utterance == t.CANCEL_CHOICE
    assert _context(bot, "c_t05_conflict_reason").cancel_reason == "UNSPECIFIED"
    action = _run(bot, "c_t05_conflict_reason", ["Hủy giúp tôi"], start=5)
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


def test_a_negated_reason_is_not_recorded_as_that_reason() -> None:
    bot, clinic = _requesting("c_t05_negated", "Tôi không bận nhưng muốn hủy lịch")
    action = _run(bot, "c_t05_negated", ["Hủy giúp tôi"], start=4)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


@pytest.mark.parametrize(
    "answer, reason",
    [
        ("Tôi không đủ tiền", "COST"),
        ("Tôi không cần khám nữa", "NO_LONGER_NEEDED"),
        ("toi khong du tien", "COST"),
    ],
)
def test_reason_negation_on_a_middle_turn_is_not_mistaken_for_abandoning_cancel(
    answer: str, reason: str
) -> None:
    """Ca review 1: chữ "không" nằm TRONG lý do, không phải lời từ chối hủy.

    Trước đây luật agreement trả REFUSE nên bot bỏ hủy và mất luôn lý do. Nay lượt này là lượt chỉ
    nêu lý do: ghi nhận lý do, giữ hành động hủy đang chờ và hỏi lại (plan T-05 §8.1 ca 1, §8.3.4).
    """
    bot, clinic = _requesting("c_t05_reason_negation")
    action = _run(bot, "c_t05_reason_negation", [answer], start=4)

    assert action.utterance == t.CANCEL_REASON_NOTED and clinic.writes == []
    ctx = _context(bot, "c_t05_reason_negation")
    assert (ctx.pending_action, ctx.cancel_reason) == ("CANCEL", reason)
    assert [e.kind for e in ctx.evidence] == ["REQUEST"]

    action = _run(bot, "c_t05_reason_negation", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED" and clinic.writes == [_cancelled("apt_00417", reason)]


def test_a_reason_with_conflicting_tokens_is_kept_but_only_gets_the_choice_question() -> None:
    """ "hôm đó tôi không đi được" có cả "không" lẫn "được" nên luật chỉ kết luận được là mơ hồ.

    Kết quả vẫn an toàn — giữ hành động hủy, ghi nhận lý do, hỏi lại — nhưng câu hỏi là câu lựa
    chọn chứ không phải câu "đã ghi nhận lý do". Đây là giới hạn của luật từ khóa; tầng ngữ nghĩa
    đọc đúng thành INFORM_REASON (`test_semantic.py`).
    """
    bot, clinic = _requesting("c_t05_mixed_tokens")
    action = _run(bot, "c_t05_mixed_tokens", ["Hôm đó tôi không đi được"], start=4)

    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []
    ctx = _context(bot, "c_t05_mixed_tokens")
    assert (ctx.pending_action, ctx.cancel_reason) == ("CANCEL", "PATIENT_UNAVAILABLE")


def test_explicitly_refusing_cancel_wins_over_an_incidental_reason() -> None:
    """Đối chứng: lời đổi ý tường minh thắng lý do đi kèm, không bị đọc thành "chỉ nêu lý do"."""
    bot, clinic = _requesting("c_t05_refuse_with_reason", "Tôi muốn hủy lịch vì bận")
    action = _run(bot, "c_t05_refuse_with_reason", ["Không hủy nữa, dù tôi không đủ tiền"], start=4)

    assert action.state == "AWAITING_INTENT" and FACTS in action.utterance
    assert clinic.writes == []
    ctx = _context(bot, "c_t05_refuse_with_reason")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == (None, None, [])


def test_a_reason_containing_a_negation_is_recorded_but_does_not_unlock_the_write() -> None:
    """G-6 / AC-4: "hủy giúp tôi vì không cần khám nữa" mơ hồ — lưu lý do, vẫn phải hỏi lại."""
    bot, clinic = _requesting("c_t05_negation_reason")
    action = _run(bot, "c_t05_negation_reason", ["Hủy giúp tôi vì không cần khám nữa"], start=4)
    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []
    assert _context(bot, "c_t05_negation_reason").cancel_reason == "NO_LONGER_NEEDED"

    action = _run(bot, "c_t05_negation_reason", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "NO_LONGER_NEEDED")]


# --- AC-5: đổi ý, chuyển hành động ---------------------------------------------------------------


@pytest.mark.parametrize("answer", ["Không hủy nữa", "Thôi, giữ lịch", "Không"])
def test_refusing_the_cancel_keeps_the_appointment_without_writing(answer: str) -> None:
    bot, clinic = _requesting("c_t05_refuse", "Tôi muốn hủy lịch vì bận")
    action = _run(bot, "c_t05_refuse", [answer], start=4)

    assert action.state == "AWAITING_INTENT" and FACTS in action.utterance
    assert clinic.writes == []  # không tự ghi CONFIRMED, cũng không ghi CANCELLED
    ctx = _context(bot, "c_t05_refuse")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == (None, None, [])


def test_refusing_the_cancel_while_asking_to_reschedule_goes_to_reschedule() -> None:
    """G-4: "không hủy nữa, tôi muốn đổi lịch" là đổi lịch, không phải giữ lịch."""
    bot, clinic = _requesting("c_t05_to_resched", "Tôi muốn hủy lịch vì bận")
    action = _run(bot, "c_t05_to_resched", ["Không hủy nữa, tôi muốn đổi lịch"], start=4)

    assert action.state == "OFFERING_SLOTS" and clinic.writes == []
    ctx = _context(bot, "c_t05_to_resched")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == ("RESCHEDULE", None, [])


def test_reason_does_not_survive_a_trip_through_another_action() -> None:
    """G-3 / AC-5: Cancel (bận) -> Reschedule -> Cancel không nêu lý do -> UNSPECIFIED."""
    bot, clinic = _requesting("c_t05_roundtrip", "Tôi muốn hủy lịch vì bận")
    _run(bot, "c_t05_roundtrip", ["Tôi muốn đổi lịch"], start=4)
    assert _context(bot, "c_t05_roundtrip").cancel_reason is None

    action = _run(bot, "c_t05_roundtrip", ["Thôi, tôi muốn hủy lịch"], start=5)
    assert action.utterance == t.CANCEL_RECONFIRM and clinic.writes == []
    action = _run(bot, "c_t05_roundtrip", ["Hủy giúp tôi"], start=6)
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


def test_coming_back_to_cancel_needs_a_fresh_request_and_confirmation(monkeypatch) -> None:
    """AC-5: bằng chứng trước khi đổi ý không được dùng lại."""
    bot, clinic = _requesting("c_t05_again")
    _run(bot, "c_t05_again", ["Thôi không hủy nữa"], start=4)
    assert _context(bot, "c_t05_again").evidence == []

    # Nói lại yêu cầu hủy: chỉ tạo REQUEST mới, chưa ghi
    action = _run(bot, "c_t05_again", ["Tôi vẫn muốn hủy lịch"], start=5)
    assert action.utterance == t.CANCEL_RECONFIRM and clinic.writes == []

    captured = _capture_cancel(monkeypatch, bot)
    action = _run(bot, "c_t05_again", ["Hủy giúp tôi"], start=6)
    assert action.outcome == "CANCELLED"
    assert captured[0][2] == [("REQUEST", 5), ("CONFIRMATION", 6)]


# --- AC-6: lặp mơ hồ, ngưỡng Policy, xin nhắc lại, im lặng ----------------------------------------


def test_repeating_the_same_reason_without_confirming_does_not_loop_forever() -> None:
    """§3.2.6: chỉ lần có tiến triển lý do mới là UNDERSTOOD; lặp lại tính UNCLEAR."""
    bot, clinic = _requesting("c_t05_loop")
    action = _run(bot, "c_t05_loop", ["Hôm đó tôi bận"], start=4)
    assert action.utterance == t.CANCEL_REASON_NOTED

    action = _run(bot, "c_t05_loop", ["Hôm đó tôi bận"], start=5)
    assert action.utterance == t.CANCEL_CHOICE
    ctx = _context(bot, "c_t05_loop")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)

    action = _run(bot, "c_t05_loop", ["Hôm đó tôi bận"], start=6)
    ctx = _context(bot, "c_t05_loop")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (2, 1)

    action = _run(bot, "c_t05_loop", ["Hôm đó tôi bận"], start=7)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert _cancel_writes(clinic) == []


def test_alternating_between_two_reasons_without_confirming_does_not_loop_forever() -> None:
    """Chỉ lý do đầu tiên là tiến triển; đổi qua lại giữa hai lý do tính UNCLEAR."""
    bot, clinic = _requesting("c_t05_flip")
    action = _run(bot, "c_t05_flip", ["Hôm đó tôi bận"], start=4)
    assert action.utterance == t.CANCEL_REASON_NOTED
    ctx = _context(bot, "c_t05_flip")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (0, 0)

    action = _run(bot, "c_t05_flip", ["Chi phí cao quá"], start=5)
    ctx = _context(bot, "c_t05_flip")
    # Lý do mới vẫn được ghi nhận, nhưng không reset bộ đếm
    assert action.utterance == t.CANCEL_REASON_NOTED and ctx.cancel_reason == "COST"
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)

    action = _run(bot, "c_t05_flip", ["Hôm đó tôi bận", "Chi phí cao quá"], start=6)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert _cancel_writes(clinic) == []


def test_three_unclear_answers_transfer_not_understood_without_cancelling() -> None:
    bot, clinic = _requesting("c_t05_unclear3")
    action = _run(bot, "c_t05_unclear3", ["Vâng", "Dạ", "Ừ"], start=4)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert _cancel_writes(clinic) == []


def test_two_not_understood_turns_transfer_without_cancelling() -> None:
    bot, clinic = _requesting("c_t05_nu2")
    action = _run(bot, "c_t05_nu2", ["Vợ tôi bảo thế", "Trời hôm nay đẹp"], start=4)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert _cancel_writes(clinic) == []


def test_agreement_after_a_not_understood_prompt_does_not_write() -> None:
    """T-08: "em chưa hiểu" không nhắc lại câu hỏi, nên "hủy đi" ở lượt sau trả lời câu nhắc đó."""
    bot, clinic = _requesting("c_t05_stale")
    action = _run(bot, "c_t05_stale", ["Vợ tôi bảo thế"], start=4)
    assert action.utterance == t.NOT_UNDERSTOOD
    assert _context(bot, "c_t05_stale").question.turn == 3

    action = _run(bot, "c_t05_stale", ["Hủy đi"], start=5)
    assert not action.ended and clinic.writes == []
    assert action.utterance == t.CANCEL_CHOICE


def test_repeat_request_replays_the_cancel_question_at_this_turn() -> None:
    bot, clinic = _requesting("c_t05_repeat")
    action = _run(bot, "c_t05_repeat", ["Gì cơ?"], start=4)
    assert action.utterance == t.CANCEL_RECONFIRM and clinic.writes == []
    ctx = _context(bot, "c_t05_repeat")
    assert ctx.question.turn == 4 and (ctx.unclear_streak, ctx.failed_understandings) == (0, 0)

    action = _run(bot, "c_t05_repeat", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED" and clinic.writes == [
        _cancelled("apt_00417", "UNSPECIFIED")
    ]


def test_silence_then_agreement_replays_the_cancel_question_first() -> None:
    bot, clinic = _requesting("c_t05_silence")
    action = _run(bot, "c_t05_silence", [SILENCE], start=4)
    assert action.utterance == f"{t.SILENCE} {t.CANCEL_RECONFIRM}"
    assert _context(bot, "c_t05_silence").question.turn == 4

    action = _run(bot, "c_t05_silence", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED" and clinic.writes == [
        _cancelled("apt_00417", "UNSPECIFIED")
    ]


# --- AC-7: kết quả lệnh ghi -----------------------------------------------------------------------


def test_rejected_cancel_is_a_system_error_not_a_cancellation() -> None:
    bot, clinic = _requesting("c_t05_rejected")
    clinic.fail_next("cancel_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    action = _run(bot, "c_t05_rejected", ["Hủy giúp tôi"], start=4)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert action.utterance != t.cancelled_done()
    assert _cancel_writes(clinic) == []
    # Chỉ báo TRANSFERRED vì /transfer thật sự thành công
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_invalid_state_transition_on_cancel_is_transferred() -> None:
    bot, clinic = _requesting("c_t05_invalid_state")
    clinic.fail_next("cancel_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    action = _run(bot, "c_t05_invalid_state", ["Hủy giúp tôi"], start=4)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert _cancel_writes(clinic) == []
    assert [op for _, op in clinic.requests].count("CANCELLED") == 1  # không retry


def test_timeout_before_the_write_blocks_the_turn_for_reconciliation() -> None:
    bot, clinic = _requesting("c_t05_timeout")
    clinic.fail_unknown("cancel_appointment", WRITE_MAX_SENDS)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t05_timeout", ["Hủy giúp tôi"], start=4)
    assert clinic.writes == []


def test_timeout_after_the_write_is_applied_still_does_not_report_success() -> None:
    """Mock đã hủy nhưng bot không nhận được phản hồi: không nói đã hủy, không ghi thêm lệnh nào."""
    bot, clinic = _requesting("c_t05_timeout_applied")
    clinic.fail_unknown("cancel_appointment", WRITE_MAX_SENDS, apply_first=True)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t05_timeout_applied", ["Hủy giúp tôi"], start=4)
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


def test_two_hundred_with_a_wrong_status_is_not_reported_as_cancelled() -> None:
    """G-5: 2xx nhưng bản ghi không ở CANCELLED -> đối soát, không ghi /transfer thay thế."""
    bot, clinic = _requesting("c_t05_status")
    clinic.cancel_appointment = lambda *args, **kwargs: {
        **clinic.appointments["apt_00417"],
        "status": "SCHEDULED",
    }
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t05_status", ["Hủy giúp tôi"], start=4)
    assert clinic.writes == []


def test_version_conflict_retries_once_with_the_same_key() -> None:
    bot, clinic = _requesting("c_t05_version")
    clinic.fail_next("cancel_appointment", clinic_error(409, "VERSION_CONFLICT"))
    action = _run(bot, "c_t05_version", ["Hủy giúp tôi"], start=4)

    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]  # ghi đúng một lần
    keys = [key for key, label in clinic.requests if label == "CANCELLED"]
    assert keys == ["c_t05_version:4:cancel"] * 2


# --- AC-8: gửi lại lượt, cách ly giữa các cuộc gọi -------------------------------------------------


def test_resending_a_request_turn_does_not_duplicate_the_evidence() -> None:
    bot, clinic = _requesting("c_t05_replay_request")
    _run(bot, "c_t05_replay_request", ["Tôi muốn hủy lịch"], start=3)
    assert [e.kind for e in _context(bot, "c_t05_replay_request").evidence] == ["REQUEST"]
    assert clinic.writes == []


def test_resending_the_cancelled_turn_raises_call_ended_without_writing_twice() -> None:
    bot, clinic = _requesting("c_t05_replay_done")
    assert _run(bot, "c_t05_replay_done", ["Hủy giúp tôi"], start=4).outcome == "CANCELLED"
    with pytest.raises(CallEnded):
        _run(bot, "c_t05_replay_done", ["Hủy giúp tôi"], start=4)
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


def test_two_calls_do_not_share_a_cancel_reason() -> None:
    clinic = FakeClinicAPI()
    first, _ = _requesting("c_t05_iso_a", "Tôi muốn hủy lịch vì bận", clinic)
    assert _context(first, "c_t05_iso_a").cancel_reason == "PATIENT_UNAVAILABLE"

    clinic.seed_appointment(
        {**clinic.appointments["apt_00417"], "appointment_id": "apt_00418", "status": "SCHEDULED"},
        slot_id="slot_77bb",
    )
    second = create_orchestrator(clinic)
    second.start_call(
        CallStart(call_id="c_t05_iso_b", direction="outbound", appointment_id="apt_00418")
    )
    _run(second, "c_t05_iso_b", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch"])
    assert _context(second, "c_t05_iso_b").cancel_reason is None

    action = _run(second, "c_t05_iso_b", ["Hủy giúp tôi"], start=4)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00418", "UNSPECIFIED")]


# --- AC-9: ngoại lệ Policy trong lúc chờ xác nhận hủy ----------------------------------------------


@pytest.mark.parametrize(
    "answer, reason",
    [
        ("Hủy đi, mà tôi đang đau ngực", "CLINICAL_QUESTION"),
        ("Cho tôi gặp nhân viên", "PATIENT_REQUEST"),
        ("Tôi muốn hỏi về bảo hiểm", "OUT_OF_SCOPE"),
        ("hủy thì mất phí không em?", "OUT_OF_SCOPE"),
        ("Tôi là vợ anh ấy", "IDENTITY_FAILED"),
    ],
)
def test_policy_exceptions_transfer_without_cancelling(answer: str, reason: str) -> None:
    bot, clinic = _requesting("c_t05_exception")
    action = _run(bot, "c_t05_exception", [answer], start=4)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)
    assert _cancel_writes(clinic) == []


def test_three_silent_turns_while_waiting_mark_unreachable_without_cancelling() -> None:
    bot, clinic = _requesting("c_t05_silent3")
    action = _run(bot, "c_t05_silent3", [SILENCE, SILENCE, SILENCE], start=4)
    assert (action.outcome, action.unreachable_reason) == ("UNREACHABLE", "SILENCE")
    assert _cancel_writes(clinic) == []


def test_a_voicemail_line_while_waiting_is_not_taken_as_a_confirmation() -> None:
    """Sau xác minh, IE không còn xét line_signal (§4.2.5) — câu này chỉ là không hiểu, không hủy."""
    bot, clinic = _requesting("c_t05_vm")
    action = _run(bot, "c_t05_vm", ["Quý khách vui lòng để lại lời nhắn sau tiếng bíp"], start=4)
    assert not action.ended and clinic.writes == []
    assert [e.kind for e in _context(bot, "c_t05_vm").evidence] == ["REQUEST"]


# --- AC-10: phạm vi (trước xác minh, inbound) ------------------------------------------------------


def test_cancel_request_before_verification_neither_discloses_nor_writes() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(
        CallStart(call_id="c_t05_early", direction="outbound", appointment_id="apt_00417")
    )
    action = _run(bot, "c_t05_early", ["Tôi muốn hủy lịch khám"])

    assert action.utterance == t.ASK_NAME_FOR_REQUEST and clinic.writes == []
    assert FACTS not in action.utterance
    ctx = _context(bot, "c_t05_early")
    assert (ctx.pending_action, ctx.cancel_reason) == (None, None)


def test_intent_said_at_the_identity_step_does_not_replace_the_request_after_verification() -> None:
    """T-02: "tôi muốn hủy" nói lúc đọc tên không tạo REQUEST — sau xác minh vẫn phải nêu lại."""
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(
        CallStart(call_id="c_t05_early2", direction="outbound", appointment_id="apt_00417")
    )
    _run(bot, "c_t05_early2", ["Tôi muốn hủy lịch vì bận", "Nguyễn Văn A", "14/03/1978"])
    ctx = _context(bot, "c_t05_early2")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == (None, None, [])
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK

    action = _run(bot, "c_t05_early2", ["Hủy giúp tôi"], start=4)
    assert not action.ended and clinic.writes == []


def test_inbound_cancel_request_is_out_of_scope_and_writes_nothing() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id="c_t05_in", direction="inbound", caller_number="0912345600"))
    action = _run(bot, "c_t05_in", ["Nguyễn Văn A", "14/03/1978"])
    assert action.utterance == t.ASK_INTENT_INBOUND

    action = _run(bot, "c_t05_in", ["Tôi muốn hủy lịch khám"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "OUT_OF_SCOPE")
    assert clinic.writes == []


# --- AC-12: hồi quy sang các luồng khác -------------------------------------------------------------


def test_cancel_from_the_attendance_question_still_needs_two_turns() -> None:
    bot, clinic, _ = _verified("c_t05_from_attendance")
    action = _run(bot, "c_t05_from_attendance", ["Tôi không đến được, hủy giúp tôi"], start=3)
    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []

    action = _run(bot, "c_t05_from_attendance", ["Hủy giúp tôi"], start=4)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "PATIENT_UNAVAILABLE")]


def test_cancel_asked_while_choosing_a_slot_starts_a_fresh_cancel_request() -> None:
    bot, clinic, _ = _verified("c_t05_from_slots")
    _run(bot, "c_t05_from_slots", ["Tôi muốn đổi lịch"], start=3)
    action = _run(bot, "c_t05_from_slots", ["Thôi, tôi muốn hủy lịch luôn"], start=4)

    assert action.utterance == t.CANCEL_RECONFIRM and clinic.writes == []
    ctx = _context(bot, "c_t05_from_slots")
    assert (ctx.pending_action, ctx.selected_slot_id) == ("CANCEL", None)
    assert [(e.kind, e.turn) for e in ctx.evidence] == [("REQUEST", 4)]


def test_confirming_attendance_is_unaffected_by_the_cancel_changes() -> None:
    bot, clinic, _ = _verified("c_t05_regression_confirm")
    action = _run(bot, "c_t05_regression_confirm", ["Vâng"], start=3)
    assert (action.outcome, action.ended) == ("CONFIRMED", True)
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


# === §8 Tầng ngữ nghĩa: Orchestrator thật + `SemanticExtractor` giả, không gọi model thật ===
# Kết quả model phải đi đúng nhánh Dialogue, KHÔNG mở khóa lệnh ghi, và mọi ràng buộc ở trên
# (hai lượt, bằng chứng, kết quả API) vẫn nguyên vẹn.


class FakeSemantic:
    """Trả kết quả đã dựng sẵn theo transcript; ghi lại mọi context để kiểm ranh giới dữ liệu."""

    def __init__(self, replies: dict[str, Optional[SemanticOutcome]]) -> None:
        self._replies = replies
        self.seen: list[SemanticContext] = []

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        self.seen.append(context)
        return self._replies.get(context.transcript.strip().lower())


class BrokenSemantic:
    """Adapter ném lỗi — lỗi tuyến sau không được làm hỏng lượt gọi."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        self.calls += 1
        raise RuntimeError("provider down")


def _requesting_with(semantic, call_id: str, request: str = "Tôi muốn hủy lịch"):
    """Như `_requesting`, nhưng gắn `SemanticExtractor` giả vào Orchestrator trước khi gọi."""
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot._extractor._semantic = semantic
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    action = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978", request])
    assert action.utterance == t.CANCEL_RECONFIRM and clinic.writes == []
    return bot, clinic


# --- §8 tầng ngữ nghĩa: model làm rõ lý do ---------------------------------------------------------------


def test_a_reason_read_by_the_model_is_kept_and_written_after_a_real_confirmation() -> None:
    """ "ngày đó tôi phải có mặt ở cơ quan": luật không có từ khóa nào, model đọc ra lý do."""
    line = "Ngày đó tôi phải có mặt ở cơ quan"
    semantic = FakeSemantic(
        {
            line.lower(): SemanticOutcome(
                ReplyKind.INFORM_REASON,
                cancel_reason="PATIENT_UNAVAILABLE",
                reason_span="phải có mặt ở cơ quan",
            )
        }
    )
    bot, clinic = _requesting_with(semantic, "c_sem_reason")

    action = _run(bot, "c_sem_reason", [line], start=4)
    assert action.utterance == t.CANCEL_REASON_NOTED and clinic.writes == []
    ctx = _context(bot, "c_sem_reason")
    assert (ctx.pending_action, ctx.cancel_reason) == ("CANCEL", "PATIENT_UNAVAILABLE")
    assert [e.kind for e in ctx.evidence] == ["REQUEST"]

    # Vẫn phải có lượt xác nhận riêng mới được ghi
    action = _run(bot, "c_sem_reason", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "PATIENT_UNAVAILABLE")]


def test_the_model_cannot_turn_a_reason_into_a_cancellation() -> None:
    """Model nói CONFIRM_ACTION cho một câu chỉ nêu lý do: vẫn không ghi (SF-05)."""
    line = "Ngày đó tôi phải có mặt ở cơ quan"
    semantic = FakeSemantic(
        {line.lower(): SemanticOutcome(ReplyKind.CONFIRM_ACTION, reply_span="phải có mặt")}
    )
    bot, clinic = _requesting_with(semantic, "c_sem_no_promote")
    action = _run(bot, "c_sem_no_promote", [line], start=4)

    assert not action.ended and clinic.writes == []
    assert _context(bot, "c_sem_no_promote").pending_action == "CANCEL"


# --- Model nhận đổi ý ---------------------------------------------------------------------


def test_change_intent_moves_to_reschedule_and_drops_the_cancel_data() -> None:
    line = "Không hủy nữa, chuyển sang tuần sau nhé"
    semantic = FakeSemantic(
        {
            line.lower(): SemanticOutcome(
                ReplyKind.CHANGE_INTENT,
                reply_span="chuyển sang tuần sau nhé",
                intent=Intent.RESCHEDULE,
                intent_span="chuyển sang tuần sau",
            )
        }
    )
    bot, clinic = _requesting_with(semantic, "c_sem_change", "Tôi muốn hủy lịch vì bận")

    action = _run(bot, "c_sem_change", [line], start=4)
    assert action.state == "OFFERING_SLOTS" and clinic.writes == []
    ctx = _context(bot, "c_sem_change")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == ("RESCHEDULE", None, [])


def test_decline_action_abandons_the_cancel_without_writing() -> None:
    line = "Thôi, cứ để nguyên như cũ đi em"
    semantic = FakeSemantic(
        {line.lower(): SemanticOutcome(ReplyKind.DECLINE_ACTION, reply_span="cứ để nguyên như cũ")}
    )
    bot, clinic = _requesting_with(semantic, "c_sem_decline", "Tôi muốn hủy lịch vì bận")

    action = _run(bot, "c_sem_decline", [line], start=4)
    assert action.state == "AWAITING_INTENT" and FACTS in action.utterance
    assert clinic.writes == []
    ctx = _context(bot, "c_sem_decline")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.evidence) == (None, None, [])


# --- Lỗi model: nhánh hỏi lại, không thành lỗi Clinic -----------------------------------------


def test_a_broken_model_still_keeps_the_grounded_rule_reason_and_asks_again() -> None:
    """§8.6.1 dòng cuối: model timeout trên "không đủ tiền" không được biến thành bỏ hủy."""
    broken = BrokenSemantic()
    bot, clinic = _requesting_with(broken, "c_sem_broken")

    action = _run(bot, "c_sem_broken", ["Tôi không đủ tiền"], start=4)
    assert broken.calls == 1
    assert action.utterance == t.CANCEL_REASON_NOTED and clinic.writes == []
    ctx = _context(bot, "c_sem_broken")
    assert (ctx.pending_action, ctx.cancel_reason) == ("CANCEL", "COST")


def test_a_model_error_does_not_end_the_call_or_write_to_clinic() -> None:
    broken = BrokenSemantic()
    bot, clinic = _requesting_with(broken, "c_sem_error")
    action = _run(bot, "c_sem_error", ["Ờ thì cũng không biết nữa"], start=4)
    assert not action.ended and action.outcome is None and clinic.writes == []


# --- Ranh giới dữ liệu và số lần gọi ------------------------------------------------------------


def test_the_model_is_called_at_most_once_per_turn_and_never_for_settled_answers() -> None:
    semantic = FakeSemantic({})
    bot, clinic = _requesting_with(semantic, "c_sem_budget")

    _run(bot, "c_sem_budget", ["Vâng"], start=4)  # đáp lễ: rule xử lý
    assert semantic.seen == []

    _run(bot, "c_sem_budget", ["Thôi thì hủy giúp tôi vậy"], start=5)
    assert len(semantic.seen) == 1  # đúng một request cho cả lượt

    _run(bot, "c_sem_budget", ["Hủy giúp tôi"], start=6)
    assert len(semantic.seen) == 1  # câu rõ toàn câu: không gọi thêm
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]


def test_the_context_given_to_the_model_carries_no_patient_or_appointment_data() -> None:
    semantic = FakeSemantic({})
    bot, _ = _requesting_with(semantic, "c_sem_privacy", "Tôi muốn hủy lịch vì bận")
    _run(bot, "c_sem_privacy", ["Ừ thì cũng tùy em thôi"], start=4)

    assert semantic.seen, "lượt này phải được định tuyến tới model"
    for context in semantic.seen:
        dumped = repr(context)
        for secret in ("Nguyễn Văn A", "1978-03-14", "pt_3391", "apt_00417", "Times City", "slot_"):
            assert secret not in dumped
        assert context.question_id is QuestionId.CANCEL_RECONFIRM
        assert context.pending_action == "CANCEL"


def test_a_stale_question_is_flagged_and_still_blocked_by_the_guardrail() -> None:
    """T-08: model biết câu hỏi không ở lượt ngay trước; guardrail vẫn chặn riêng."""
    line = "Thôi thì hủy giúp tôi vậy"
    semantic = FakeSemantic(
        {line.lower(): SemanticOutcome(ReplyKind.CONFIRM_ACTION, reply_span="hủy giúp tôi")}
    )
    bot, clinic = _requesting_with(semantic, "c_sem_stale")

    # "em chưa hiểu" không nhắc lại câu hỏi -> câu hỏi đang chờ vẫn ở lượt 3
    _run(bot, "c_sem_stale", ["Vợ tôi bảo thế"], start=4)
    action = _run(bot, "c_sem_stale", [line], start=5)

    assert not action.ended and clinic.writes == []
    assert semantic.seen[-1].answers_last_question is False


@pytest.mark.parametrize(
    "answer, reason",
    [("Tôi đau ngực quá", "CLINICAL_QUESTION"), ("Cho tôi gặp nhân viên", "PATIENT_REQUEST")],
)
def test_policy_exceptions_never_reach_the_model(answer: str, reason: str) -> None:
    semantic = FakeSemantic({})
    bot, clinic = _requesting_with(semantic, "c_sem_policy")
    action = _run(bot, "c_sem_policy", [answer], start=4)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)
    assert semantic.seen == []
    assert all(status != "CANCELLED" for _, status, _ in clinic.writes)


def test_silence_never_reaches_the_model() -> None:
    semantic = FakeSemantic({})
    bot, _ = _requesting_with(semantic, "c_sem_silence")
    bot.handle_turn("c_sem_silence", CallerInput(turn=4, text=None, silence_ms=2000))
    assert semantic.seen == []


def test_changing_to_keep_the_appointment_abandons_the_cancel_instead_of_not_understood() -> None:
    """Model đọc "tôi vẫn đi khám" là CHANGE_INTENT -> CONFIRM: giữ lịch, không "em chưa hiểu"."""
    line = "Không hủy nữa, tôi vẫn đi khám"
    semantic = FakeSemantic(
        {
            line.lower(): SemanticOutcome(
                ReplyKind.CHANGE_INTENT,
                reply_span="tôi vẫn đi khám",
                intent=Intent.CONFIRM,
                intent_span="tôi vẫn đi khám",
            )
        }
    )
    bot, clinic = _requesting_with(semantic, "c_sem_keep", "Tôi muốn hủy lịch vì bận")

    action = _run(bot, "c_sem_keep", [line], start=4)
    assert len(semantic.seen) == 1
    assert action.utterance != t.NOT_UNDERSTOOD
    assert action.state == "AWAITING_INTENT" and FACTS in action.utterance
    assert clinic.writes == []
    ctx = _context(bot, "c_sem_keep")
    assert (ctx.pending_action, ctx.cancel_reason, ctx.failed_understandings) == (None, None, 0)


# --- Demo 22-09: "Dạo này kẹt tiền quá em ạ" -------------------------------------------------------

KET_TIEN = "Dạo này kẹt tiền quá em ạ"


class _TimeoutGateway:
    """LLM gateway luôn hết thời gian — đi qua adapter thật, không gọi mạng."""

    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(self, messages, **kwargs) -> StructuredReply:
        self.calls += 1
        return StructuredReply("timeout")


def test_a_cost_reason_read_by_the_model_is_kept_until_the_cancel() -> None:
    semantic = FakeSemantic(
        {
            KET_TIEN.lower(): SemanticOutcome(
                ReplyKind.INFORM_REASON, cancel_reason="COST", reason_span="kẹt tiền"
            )
        }
    )
    bot, clinic = _requesting_with(semantic, "c_sem_ket_tien")

    action = _run(bot, "c_sem_ket_tien", [KET_TIEN], start=4)
    assert action.utterance == t.CANCEL_REASON_NOTED and clinic.writes == []
    assert _context(bot, "c_sem_ket_tien").cancel_reason == "COST"

    action = _run(bot, "c_sem_ket_tien", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "COST")]


def test_a_semantic_timeout_asks_again_instead_of_a_contradiction() -> None:
    """Luật chưa nhận ra "kẹt tiền"; "ạ" cuối câu không còn là tín hiệu mâu thuẫn -> nhánh chưa hiểu.

    Từ điển lý do giữ nguyên, nên lượt xác nhận sau ghi UNSPECIFIED — giới hạn đã chấp nhận.
    """
    gateway = _TimeoutGateway()
    semantic = LLMSemanticExtractor(gateway, max_input_chars=1500, max_completion_tokens=400)
    bot, clinic = _requesting_with(semantic, "c_sem_ket_tien_timeout")

    action = _run(bot, "c_sem_ket_tien_timeout", [KET_TIEN], start=4)
    assert gateway.calls == 1
    assert action.utterance == t.NOT_UNDERSTOOD and action.utterance != t.CANCEL_CHOICE
    assert not action.ended and clinic.writes == []
    assert _context(bot, "c_sem_ket_tien_timeout").pending_action == "CANCEL"

    # "Em chưa hiểu" không nhắc lại câu xác nhận (T-08): lượt này hỏi lại, lượt sau mới là xác nhận
    action = _run(bot, "c_sem_ket_tien_timeout", ["Hủy giúp tôi"], start=5)
    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []
    action = _run(bot, "c_sem_ket_tien_timeout", ["Hủy lịch"], start=6)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [_cancelled("apt_00417", "UNSPECIFIED")]
