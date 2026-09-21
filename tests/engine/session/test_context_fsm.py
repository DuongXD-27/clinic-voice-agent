"""F-03: context lưu–đọc đầy đủ, FSM chặn chuyển state sai, bằng chứng chỉ hợp lệ cho hành động chờ."""

from datetime import date, datetime

import pytest

from callbot.engine.extraction.schema import VN_TZ, QuestionId
from callbot.engine.policy.guardrails import SevereFailureBlocked, assert_action_confirmed
from callbot.engine.session.context import ActionEvidence, CallContext, HistoryItem, Question
from callbot.engine.session.fsm import (
    IllegalTransition,
    InconsistentSession,
    check_write,
)
from callbot.engine.session.manager import SessionManager
from callbot.engine.types import CallStart

SLOTS = [
    {"slot_id": "slot_a", "starts_at": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "slot_b", "starts_at": "2026-10-14T14:30:00+07:00"},
]


def _ctx(**overrides) -> CallContext:
    ctx = CallContext(
        call=CallStart(call_id="c_ctx", direction="outbound", appointment_id="apt_00417"),
        opened_at=datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ),
        # Hồ sơ đã đọc ở lượt 0 (T-01); FSM đòi có khi đã xác minh (T-02)
        identity_lookup="LOADED",
        patient_id="pt_3391",
    )
    for name, value in overrides.items():
        setattr(ctx, name, value)
    return ctx


def _evidence(kind, action, turn, question_id, slot_id=None, label="AGREE", question_turn=None):
    return ActionEvidence(
        kind=kind,
        action=action,
        slot_id=slot_id,
        turn=turn,
        question_id=question_id,
        question_turn=question_turn if question_turn is not None else turn - 1,
        transcript="...",
        label=label,
        provenance="EXACT",
        span="...",
    )


def _verified_resched(turn: int = 5) -> CallContext:
    ctx = _ctx(
        identity_step="VERIFIED", state="AWAITING_CONFIRMATION", turn=turn, slots=list(SLOTS)
    )
    ctx.set_pending("RESCHEDULE", "slot_b")
    ctx.question = Question(QuestionId.SLOT_READBACK, "chốt?", turn - 1, "RESCHEDULE", "slot_b")
    return ctx


def test_context_roundtrip_keeps_every_field() -> None:
    ctx = _verified_resched()
    ctx.claimed_name = "nguyễn văn a"
    ctx.claimed_dob = date(1978, 3, 14)
    ctx.patient_id = "pt_3391"
    ctx.presented_slot_ids = ["slot_b", "slot_a"]
    ctx.add_evidence(_evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_b"))
    ctx.cancel_reason = "COST"
    ctx.failed_understandings, ctx.unclear_streak, ctx.silent_turns = 1, 1, 2
    ctx.history = [HistoryItem(4, "caller", "khung 2"), HistoryItem(4, "bot", "chốt?")]

    data = ctx.to_dict()
    assert data["schema_version"] == 1
    assert CallContext.from_dict(data) == ctx


def test_unknown_schema_version_is_rejected() -> None:
    data = _ctx().to_dict()
    data["schema_version"] = 99
    with pytest.raises(ValueError):
        CallContext.from_dict(data)


def test_illegal_transitions_are_blocked() -> None:
    ctx = _ctx()
    with pytest.raises(IllegalTransition):
        SessionManager.transition(ctx, "AWAITING_INTENT")  # chưa xác minh
    ended = _ctx(state="ENDED", outcome="TRANSFERRED")
    with pytest.raises(IllegalTransition):
        SessionManager.transition(ended, "AWAITING_IDENTITY")
    with pytest.raises(IllegalTransition):
        SessionManager.close(ended, "CONFIRMED")


@pytest.mark.parametrize(
    "overrides",
    [
        {"identity_lookup": "PENDING"},  # chưa đọc hồ sơ ở lượt 0
        {"identity_lookup": "NO_CANDIDATES"},  # không có hồ sơ để đối chiếu
        {"identity_lookup": "UNAVAILABLE"},
        {"patient_id": None},  # không biết đúng bệnh nhân
    ],
)
def test_verified_requires_loaded_reference_and_patient(overrides) -> None:
    """T-02: 'đã xác minh' chỉ hợp lệ khi đã đối chiếu với hồ sơ đọc ở lượt 0 và có patient_id."""
    ctx = _ctx(identity_step="VERIFIED", **overrides)
    with pytest.raises(InconsistentSession):
        SessionManager.transition(ctx, "AWAITING_INTENT")
    assert ctx.state == "AWAITING_IDENTITY"


def test_close_goes_through_fsm_and_is_terminal() -> None:
    ctx = _ctx()
    SessionManager.close(ctx, "TRANSFERRED", transfer_reason="IDENTITY_FAILED")
    assert (ctx.state, ctx.outcome, ctx.transfer_reason) == (
        "ENDED",
        "TRANSFERRED",
        "IDENTITY_FAILED",
    )
    with pytest.raises(IllegalTransition):
        SessionManager.close(ctx, "CONFIRMED")


def test_awaiting_confirmation_requires_consistent_pending_action() -> None:
    ctx = _ctx(identity_step="VERIFIED", state="AWAITING_INTENT")
    with pytest.raises(InconsistentSession):
        SessionManager.transition(ctx, "AWAITING_CONFIRMATION")
    ctx.set_pending("RESCHEDULE", "slot_x")  # slot không có trong GET /slots
    ctx.question = Question(QuestionId.SLOT_READBACK, "?", 1, "RESCHEDULE", "slot_x")
    with pytest.raises(InconsistentSession):
        SessionManager.transition(ctx, "AWAITING_CONFIRMATION")


def test_evidence_is_cleared_on_refusal_action_change_and_slot_change() -> None:
    ctx = _verified_resched()
    ctx.add_evidence(_evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_b"))
    ctx.select_slot("slot_a")
    assert ctx.evidence == []

    ctx.add_evidence(_evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_a"))
    ctx.set_pending("CANCEL")
    assert ctx.evidence == [] and ctx.selected_slot_id is None

    ctx.add_evidence(_evidence("REQUEST", "CANCEL", 5, QuestionId.CONFIRM_READBACK, label="CANCEL"))
    ctx.clear_pending()
    assert ctx.evidence == [] and ctx.pending_action is None


def test_evidence_must_match_pending_action_and_slot() -> None:
    ctx = _verified_resched()
    with pytest.raises(ValueError):
        ctx.add_evidence(
            _evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_a")
        )


def test_old_evidence_does_not_unlock_new_slot() -> None:
    ctx = _verified_resched()
    ctx.add_evidence(_evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_b"))
    assert_action_confirmed(ctx, "RESCHEDULE", "slot_b")

    ctx.select_slot("slot_a")
    ctx.question = Question(QuestionId.SLOT_READBACK, "?", 4, "RESCHEDULE", "slot_a")
    with pytest.raises(SevereFailureBlocked):
        assert_action_confirmed(ctx, "RESCHEDULE", "slot_a")


def test_confirmation_must_be_from_current_turn_and_right_question() -> None:
    ctx = _verified_resched(turn=6)
    ctx.add_evidence(_evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.SLOT_READBACK, "slot_b"))
    with pytest.raises(SevereFailureBlocked):
        assert_action_confirmed(ctx, "RESCHEDULE", "slot_b")  # bằng chứng của lượt trước

    ctx = _verified_resched()
    ctx.add_evidence(
        _evidence("CONFIRMATION", "RESCHEDULE", 5, QuestionId.CONFIRM_READBACK, "slot_b")
    )
    with pytest.raises(SevereFailureBlocked):
        assert_action_confirmed(ctx, "RESCHEDULE", "slot_b")


def test_confirmation_must_answer_question_asked_on_the_previous_turn() -> None:
    """T-08: câu hỏi từ hai lượt trước (xen câu nhắc chung) không nhận "vâng" của lượt này."""
    ctx = _verified_resched(turn=6)
    ctx.question = Question(QuestionId.SLOT_READBACK, "chốt?", 4, "RESCHEDULE", "slot_b")
    ctx.add_evidence(
        _evidence(
            "CONFIRMATION", "RESCHEDULE", 6, QuestionId.SLOT_READBACK, "slot_b", question_turn=4
        )
    )
    with pytest.raises(SevereFailureBlocked):
        assert_action_confirmed(ctx, "RESCHEDULE", "slot_b")


def _cancel_ctx(turn: int) -> CallContext:
    ctx = _ctx(identity_step="VERIFIED", state="AWAITING_CONFIRMATION", turn=turn)
    ctx.set_pending("CANCEL")
    ctx.question = Question(QuestionId.CANCEL_RECONFIRM, "chắc chắn hủy?", turn - 1, "CANCEL")
    return ctx


def test_cancel_needs_request_and_confirmation_in_different_turns() -> None:
    ctx = _cancel_ctx(turn=4)
    ctx.add_evidence(_evidence("CONFIRMATION", "CANCEL", 4, QuestionId.CANCEL_RECONFIRM))
    with pytest.raises(SevereFailureBlocked, match="SF-05"):
        assert_action_confirmed(ctx, "CANCEL")  # thiếu yêu cầu hủy

    ctx.add_evidence(_evidence("REQUEST", "CANCEL", 4, QuestionId.CONFIRM_READBACK, label="CANCEL"))
    with pytest.raises(SevereFailureBlocked, match="SF-05"):
        assert_action_confirmed(ctx, "CANCEL")  # cùng một lượt

    ctx = _cancel_ctx(turn=4)
    ctx.add_evidence(_evidence("REQUEST", "CANCEL", 3, QuestionId.CONFIRM_READBACK, label="CANCEL"))
    ctx.add_evidence(_evidence("CONFIRMATION", "CANCEL", 4, QuestionId.CANCEL_RECONFIRM))
    assert_action_confirmed(ctx, "CANCEL")
    check_write(ctx, "CANCEL")


def test_check_write_rejects_inconsistent_state() -> None:
    ctx = _cancel_ctx(turn=4)
    with pytest.raises(InconsistentSession):
        check_write(ctx, "CONFIRM")  # hành động chờ là CANCEL
    ctx.state = "OFFERING_SLOTS"
    with pytest.raises(InconsistentSession):
        check_write(ctx, "CANCEL")
    ended = _cancel_ctx(turn=4)
    ended.state, ended.outcome = "ENDED", "CANCELLED"
    with pytest.raises(InconsistentSession):
        check_write(ended, "CANCEL")
