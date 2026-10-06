"""R-01 — Output Guard và receipt gate trên core thật (orchestrator + FakeClinicAPI + Redis giả).

`create_orchestrator` dùng `RedisSessionStore` trên fakeredis (conftest), nên mọi ca ở đây chạy đúng
đường Redis: `finish_command(SUCCEEDED)` purge phiên ngay, receipt chỉ còn trong nhật ký RAM của lượt.
"""

from copy import deepcopy
from dataclasses import replace
from typing import Any, Optional

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    SessionStoreUnavailable,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.manager import DialogueManager
from callbot.engine.extraction import QuestionId
from callbot.engine.journal import ClinicCommand, current_journal
from callbot.engine.policy import output_guard
from callbot.engine.session import CallContext
from callbot.engine.session.manager import StoreCommandJournal
from callbot.engine.session.store import SessionRecord
from callbot.engine.types import BotAction
from callbot.tracing import Tracer
from callbot.tracing.pseudonym import CallKeyFactory
from clinic_mock_sim import FakeClinicAPI, clinic_error
from tests.engine.test_confirm_dialogue import CONFIRMED_WRITE, _at_readback
from tests.engine.test_orchestrator import SILENCE, _context, _outbound, _run


class _MemorySink:
    def __init__(self) -> None:
        self.spans: list[Any] = []

    def emit(self, span: Any) -> None:
        self.spans.append(span)


def _tracer(sink: _MemorySink) -> Tracer:
    return Tracer(
        sink, CallKeyFactory("r01-guard-test-secret-000000000000", version="v1", environment="test")
    )


def _traced_run(bot, tracer: Tracer, call_id: str, lines: list[Optional[str]], start: int = 1):
    action = None
    for turn, line in enumerate(lines, start=start):
        caller = (
            CallerInput(turn=turn, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        with tracer.start_trace(
            call_id=call_id, turn=turn, component="TURN", operation="http.call_turn"
        ):
            action = bot.handle_turn(call_id, caller)
    return action


def _guard_spans(sink: _MemorySink) -> list[dict[str, Any]]:
    return [span.to_dict() for span in sink.spans if span.component == "GUARD"]


def _operations(clinic: FakeClinicAPI, since: int) -> list[str]:
    return [record.operation for record in clinic.calls[since:]]


def _transfers(clinic: FakeClinicAPI) -> list[tuple[str, str, dict[str, Any]]]:
    return [write for write in clinic.writes if write[1] == "TRANSFERRED"]


def _spy_apply(monkeypatch, bot) -> list[tuple[list[dict[str, Any]], Any, BotAction]]:
    """Trạng thái ctx ngay TRƯỚC `_apply` — sau commit phiên kết thúc đã bị purge."""
    seen: list[tuple[list[dict[str, Any]], Any, BotAction]] = []
    apply = bot._apply

    def spy(ctx: CallContext, action: BotAction) -> None:
        seen.append((deepcopy(ctx.slots), ctx.question, action))
        apply(ctx, action)

    monkeypatch.setattr(bot, "_apply", spy)
    return seen


def _after_respond(monkeypatch, bot, mutate) -> None:
    respond = bot._dialogue.respond

    def wrapped(ctx, extraction, now):
        reply = respond(ctx, extraction, now)
        mutate(ctx)
        return reply

    monkeypatch.setattr(bot._dialogue, "respond", wrapped)


def _offering(call_id: str, clinic: Optional[FakeClinicAPI] = None):
    """Outbound đã xác minh, đang đề xuất slot (slot_aa01, slot_91d2). Lượt kế tiếp là 4."""
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound(call_id))
    action = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đổi lịch"])
    assert action.state == "OFFERING_SLOTS"
    return bot, clinic


def _assert_purged(bot, call_id: str, next_turn: int) -> None:
    session = bot.sessions.store.get_session(call_id)
    assert session.purged_reason == "ENDED" and session.context == {}
    with pytest.raises(CallEnded):
        bot.handle_turn(call_id, CallerInput(turn=next_turn, text="alo"))


# --- Receipt gate: kết quả ghi đi trước mọi fallback -----------------------------------------


def _broken_confirmed(ctx, appointment):
    raise KeyError("starts_at")


def test_render_error_after_confirm_keeps_confirmed(monkeypatch) -> None:
    """(a) G-5: không chuyển máy, không đọc lại version, không 409 — báo đúng CONFIRMED đã ghi."""
    bot, clinic, _ = _at_readback("c_r01_a")
    monkeypatch.setattr(t, "confirmed", _broken_confirmed)
    before = len(clinic.calls)

    action = _run(bot, "c_r01_a", ["vâng"], start=3)

    assert (action.outcome, action.ended, action.state) == ("CONFIRMED", True, "ENDED")
    assert action.utterance == t.DONE_SAFE["CONFIRMED"]
    assert clinic.writes == [CONFIRMED_WRITE]
    assert _operations(clinic, before) == ["get_appointment", "confirm_appointment"]
    _assert_purged(bot, "c_r01_a", 4)


def test_render_error_after_confirm_retried_once_keeps_confirmed(monkeypatch) -> None:
    """(a') Confirm thành công ở lần gửi lại sau timeout (mock đã áp dụng lần đầu)."""
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_r01_a2", clinic)
    clinic.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    monkeypatch.setattr(t, "confirmed", _broken_confirmed)

    action = _run(bot, "c_r01_a2", ["vâng"], start=3)

    assert (action.outcome, action.utterance) == ("CONFIRMED", t.DONE_SAFE["CONFIRMED"])
    assert clinic.writes == [CONFIRMED_WRITE]


def test_reschedule_with_wrong_status_requires_reconciliation() -> None:
    """(b) 2xx sai trạng thái đích: đối soát, không /transfer, không nói RESCHEDULED_DONE."""
    bot, clinic = _offering("c_r01_b")
    _run(bot, "c_r01_b", ["khung 1 được không"], start=4)
    clinic.after_next("reschedule_appointment", lambda body: body.update(status="SCHEDULED"))

    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_r01_b", ["được"], start=5)
    assert _transfers(clinic) == []


def test_blocked_success_message_is_replaced_not_transferred(monkeypatch) -> None:
    """(c) Đã ghi CONFIRMED mà câu báo không qua guard: REPLACE bằng DONE_SAFE, không /transfer."""
    sink = _MemorySink()
    tracer = _tracer(sink)
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, tracer=tracer)
    bot.start_call(_outbound("c_r01_c"))
    _run(bot, "c_r01_c", ["Nguyễn Văn A", "14/03/1978"])
    monkeypatch.setattr(
        t, "confirmed", lambda ctx, appointment: "Dạ, em đã xác nhận lịch khám khoa Tim mạch ạ."
    )

    action = _traced_run(bot, tracer, "c_r01_c", ["vâng"], start=3)

    assert (action.outcome, action.utterance) == ("CONFIRMED", t.DONE_SAFE["CONFIRMED"])
    assert clinic.writes == [CONFIRMED_WRITE]
    guard = _guard_spans(sink)[-1]
    assert (guard["guard_verdict"], guard["guard_rule"]) == ("REPLACE", "OG-0")
    assert (guard["write_operation"], guard["write_succeeded"]) == ("confirm", 1)
    replaced = [event for event in guard["events"] if event["name"] == "output_guard.replaced"]
    assert replaced[0]["attributes"] == {
        "guard_rule": "OG-0",
        "outcome": "CONFIRMED",
        "write_operation": "confirm",
    }


def test_receipt_with_wrong_status_requires_reconciliation(monkeypatch) -> None:
    """(d) Phòng thủ lớp hai: journal có SUCCEEDED sai trạng thái đích -> WriteOutcomeUnknown."""
    bot, clinic, _ = _at_readback("c_r01_d")
    entries = StoreCommandJournal.entries

    def corrupted(self):
        return [
            replace(entry, result={**entry.result, "status": "SCHEDULED"})
            if entry.status == "SUCCEEDED"
            else entry
            for entry in entries(self)
        ]

    monkeypatch.setattr(StoreCommandJournal, "entries", corrupted)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_r01_d", ["vâng"], start=3)
    assert _transfers(clinic) == []


def test_failed_unreachable_then_successful_transfer_passes_guard() -> None:
    """(e) Hai lệnh đã thử, một lệnh thành công: receipt TRANSFERRED, không bất thường."""
    sink = _MemorySink()
    tracer = _tracer(sink)
    clinic = FakeClinicAPI()
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    bot = create_orchestrator(clinic, tracer=tracer)
    bot.start_call(_outbound("c_r01_e"))

    action = _traced_run(bot, tracer, "c_r01_e", [SILENCE, SILENCE, SILENCE])

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert action.utterance == t.TRANSFER
    guard = _guard_spans(sink)[-1]
    assert guard["guard_verdict"] == "PASS"
    assert (guard["write_attempted"], guard["write_succeeded"]) == (2, 1)
    assert (guard["write_operation"], guard["write_status_match"]) == ("transfer", True)


def test_failed_unreachable_and_rejected_transfer_still_transfers() -> None:
    """(f) Chỉ có lệnh bị từ chối: fallback bình thường, vẫn TRANSFERRED theo `transfer()`."""
    clinic = FakeClinicAPI()
    for operation in ("mark_unreachable", "transfer_appointment"):
        clinic.fail_next(operation, clinic_error(409, "VERSION_CONFLICT"))
        clinic.fail_next(operation, clinic_error(409, "VERSION_CONFLICT"))
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_r01_f"))

    action = _run(bot, "c_r01_f", [SILENCE, SILENCE, SILENCE])

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert clinic.writes == []


def test_pending_write_with_ordinary_error_is_not_transferred(monkeypatch) -> None:
    """(g) Lệnh còn PENDING khi Dialogue ném lỗi thường: đối soát, không gọi /transfer."""
    bot, clinic, _ = _at_readback("c_r01_g")

    def half_sent_confirm(ctx):
        current_journal().begin(
            ClinicCommand(
                "confirm",
                "/appointments/apt_00417/confirm",
                {},
                1,
                f"{ctx.call_id}:{ctx.turn}:confirm",
            )
        )
        raise RuntimeError("bug sau khi gửi")

    monkeypatch.setattr(bot._dialogue._gateway, "confirm", half_sent_confirm)
    transfer_after_error = []
    monkeypatch.setattr(
        bot, "_transfer_after_error", lambda *args: transfer_after_error.append(args)
    )

    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_r01_g", ["vâng"], start=3)
    assert transfer_after_error == [] and clinic.writes == []


@pytest.mark.parametrize(
    ("state", "ended"),
    [("ENDED", False), ("AWAITING_INTENT", True)],
)
def test_success_that_does_not_close_the_session_is_replaced(monkeypatch, state, ended) -> None:
    """(h) Đúng outcome nhưng quên đóng phiên: gate bắt trước `_apply`, không để commit ném lỗi."""
    bot, clinic, _ = _at_readback(f"c_r01_h_{state}")
    monkeypatch.setattr(
        DialogueManager,
        "_finish",
        staticmethod(lambda outcome, text: BotAction(text, state, ended=ended, outcome=outcome)),
    )

    action = _run(bot, f"c_r01_h_{state}", ["vâng"], start=3)

    assert (action.outcome, action.ended, action.state) == ("CONFIRMED", True, "ENDED")
    assert action.utterance == t.DONE_SAFE["CONFIRMED"]
    assert clinic.writes == [CONFIRMED_WRITE]
    assert bot.sessions.store.get_session(f"c_r01_h_{state}").purged_reason == "ENDED"


def test_transfer_reason_that_differs_from_receipt_is_replaced(monkeypatch) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_r01_h_reason"))
    transfer = bot._dialogue.transfer

    def wrong_reason(ctx, reason):
        return replace(transfer(ctx, reason), transfer_reason="OUT_OF_SCOPE")

    monkeypatch.setattr(bot._dialogue, "transfer", wrong_reason)
    action = _run(bot, "c_r01_h_reason", ["cho tôi gặp nhân viên"])

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert _transfers(clinic) == [
        ("apt_00417", "TRANSFERRED", {"transfer_reason": "PATIENT_REQUEST"})
    ]


# --- Receipt trên Redis ---------------------------------------------------------------------


def test_receipt_survives_redis_purge(store) -> None:
    store.create_session(
        SessionRecord(call_id="c_r01_redis", start_config={}, opening={}, context={})
    )
    store.reserve_turn("c_r01_redis", 1, {"text": "vâng"}, _context_time())
    journal = StoreCommandJournal(store, "c_r01_redis", 1)
    command = ClinicCommand("confirm", "/appointments/apt_00417/confirm", {}, 1, "k:1:confirm")
    result = {"appointment_id": "apt_00417", "status": "CONFIRMED", "starts_at": "x"}

    journal.begin(command)
    journal.succeeded(command, result)
    result["status"] = "SCHEDULED"  # Dialogue sửa dict trả về không đổi receipt

    session = store.get_session("c_r01_redis")
    assert session.purged_reason == "CLINIC_COMMITTED" and session.context == {}
    assert [record.result for record in store.list_commands("c_r01_redis")] == [None]
    [entry] = journal.entries()
    assert (entry.status, entry.command, entry.result["status"]) == (
        "SUCCEEDED",
        command,
        "CONFIRMED",
    )
    assert output_guard.receipt_gate(journal.entries()).outcome == "CONFIRMED"


def _context_time():
    from callbot.engine.session.manager import now_vn

    return now_vn()


def test_store_failure_on_success_leaves_no_receipt(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_r01_store")
    store = bot.sessions.store
    finish = store.finish_command
    journals: list[StoreCommandJournal] = []
    begin = StoreCommandJournal.begin

    def remember(self, command):
        journals.append(self)
        begin(self, command)

    def failing_finish(call_id, key, status, **kwargs):
        if status == "SUCCEEDED":
            raise SessionStoreUnavailable("redis down")
        return finish(call_id, key, status, **kwargs)

    monkeypatch.setattr(StoreCommandJournal, "begin", remember)
    monkeypatch.setattr(store, "finish_command", failing_finish)

    with pytest.raises(SessionStoreUnavailable):
        _run(bot, "c_r01_store", ["vâng"], start=3)
    assert [entry.status for entry in journals[-1].entries()] == ["PENDING"]
    assert _transfers(clinic) == []


# --- OG-6 trên core thật --------------------------------------------------------------------


def test_in_place_slot_edit_is_blocked_and_restored_before_commit(monkeypatch) -> None:
    bot, clinic = _offering("c_r01_og6_slots")
    original = deepcopy(_context(bot, "c_r01_og6_slots").slots)
    seen = _spy_apply(monkeypatch, bot)
    _after_respond(
        monkeypatch, bot, lambda ctx: ctx.slots[0].update(starts_at="2026-10-14T07:00:00+07:00")
    )

    action = _run(bot, "c_r01_og6_slots", ["chờ tôi một chút"], start=4)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    slots, question, applied = seen[-1]
    assert applied is action and slots == original and question is None
    assert _transfers(clinic) == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]
    _assert_purged(bot, "c_r01_og6_slots", 5)


def test_question_text_changed_after_ask_is_blocked(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_r01_og6_ask")
    seen = _spy_apply(monkeypatch, bot)
    _after_respond(
        monkeypatch,
        bot,
        lambda ctx: setattr(ctx, "question", replace(ctx.question, text=t.CANCEL_RECONFIRM)),
    )

    action = _run(bot, "c_r01_og6_ask", ["chắc là được"], start=3)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert seen[-1][1] is None
    _assert_purged(bot, "c_r01_og6_ask", 4)


def test_old_question_edited_without_new_ask_is_blocked(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_r01_og6_old")
    _after_respond(
        monkeypatch,
        bot,
        lambda ctx: setattr(ctx, "question", replace(ctx.question, text=t.CANCEL_RECONFIRM)),
    )

    action = _run(bot, "c_r01_og6_old", ["chờ tôi một chút"], start=3)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")


def test_legitimate_rereads_are_not_blocked() -> None:
    bot, clinic, summary = _at_readback("c_r01_reread")

    silence = _run(bot, "c_r01_reread", [SILENCE], start=3)
    assert silence.utterance == t.silence_reprompt(summary.utterance)
    assert _context(bot, "c_r01_reread").question.turn == 3

    hold = _run(bot, "c_r01_reread", ["chờ tôi một chút"], start=4)
    assert hold.utterance == t.HOLD
    assert _context(bot, "c_r01_reread").question.turn == 3

    repeat = _run(bot, "c_r01_reread", ["anh nói lại giúp tôi được không"], start=5)
    assert repeat.utterance == summary.utterance and not repeat.ended
    question = _context(bot, "c_r01_reread").question
    assert (question.question_id, question.turn) == (QuestionId.CONFIRM_READBACK, 5)
    assert clinic.writes == []


def test_unsent_question_before_policy_transfer_is_dropped(monkeypatch) -> None:
    """Dialogue hỏi lại rồi Policy chuyển máy NOT_UNDERSTOOD: câu chưa phát bị bỏ, không bị chặn."""
    bot, clinic, _ = _at_readback("c_r01_unsent")
    seen = _spy_apply(monkeypatch, bot)

    action = _run(bot, "c_r01_unsent", ["chắc là được", "có lẽ vậy", "để tôi xem đã"], start=3)

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert action.utterance == t.TRANSFER
    assert seen[-1][1] is None
    assert _transfers(clinic) == [
        ("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})
    ]


def test_opening_blocked_creates_no_session(monkeypatch) -> None:
    from callbot.engine.dialogue import outbound
    from callbot.engine.errors import CallStartBlocked

    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    opening = outbound.opening
    monkeypatch.setattr(
        outbound,
        "opening",
        lambda ctx, verifier: BotAction("Lịch khám của anh chị lúc 9 giờ", "AWAITING_IDENTITY"),
    )
    call = CallStart(call_id="c_r01_open", direction="outbound", appointment_id="apt_00417")
    with pytest.raises(CallStartBlocked):
        bot.start_call(call)
    assert bot.sessions.store.get_session("c_r01_open") is None and clinic.writes == []

    monkeypatch.setattr(outbound, "opening", opening)
    assert bot.start_call(call).utterance == t.GREETING_OUTBOUND


# --- Lỗi trong fallback sau khi /transfer đã ghi thành công ---------------------------------


def _break_after_transfer_write(monkeypatch, bot) -> None:
    transfer = bot._dialogue.transfer

    def broken(ctx, reason):
        transfer(ctx, reason)  # /transfer đã ghi, receipt TRANSFERRED đã có
        raise KeyError("lỗi sau khi ghi")

    monkeypatch.setattr(bot._dialogue, "transfer", broken)


def _assert_transferred_once(bot, clinic: FakeClinicAPI, call_id: str, action: BotAction) -> None:
    assert (action.outcome, action.transfer_reason, action.ended) == (
        "TRANSFERRED",
        "SYSTEM_ERROR",
        True,
    )
    assert action.utterance == t.TRANSFER
    assert _transfers(clinic) == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]
    # Lượt đã commit: không kẹt ở CLINIC_COMMITTED chờ đối soát
    assert bot.sessions.store.get_session(call_id).purged_reason == "ENDED"


def test_error_in_fallback_after_dialogue_error_keeps_transferred(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_r01_fb_dialogue")
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    _break_after_transfer_write(monkeypatch, bot)

    action = _run(bot, "c_r01_fb_dialogue", ["vâng"], start=3)

    _assert_transferred_once(bot, clinic, "c_r01_fb_dialogue", action)


def test_error_in_fallback_after_guard_block_keeps_transferred(monkeypatch) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_r01_fb_guard"))
    monkeypatch.setattr(
        t, "appointment_summary", lambda ctx, appointment: "Lịch khám khoa Tim mạch lúc 9 giờ."
    )
    _break_after_transfer_write(monkeypatch, bot)

    action = _run(bot, "c_r01_fb_guard", ["Nguyễn Văn A", "14/03/1978"])

    _assert_transferred_once(bot, clinic, "c_r01_fb_guard", action)


def test_error_in_fallback_before_any_write_still_raises(monkeypatch) -> None:
    """Chưa có receipt: không tự báo TRANSFERRED; lượt còn PROCESSING nên gửi lại xử lý được."""
    bot, clinic, _ = _at_readback("c_r01_fb_nowrite")
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))

    def broken(ctx, reason):
        raise KeyError("lỗi trước khi ghi")

    monkeypatch.setattr(bot._dialogue, "transfer", broken)
    with pytest.raises(KeyError):
        _run(bot, "c_r01_fb_nowrite", ["vâng"], start=3)
    assert _transfers(clinic) == []
    assert bot.sessions.store.get_session("c_r01_fb_nowrite").purged_reason is None
