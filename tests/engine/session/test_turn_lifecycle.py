"""F-03: replay, thứ tự lượt, đồng thời, restart và gián đoạn trên Redis."""

import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

from callbot.engine import (
    CallBusy,
    CallConflict,
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    SessionNotFound,
    SessionStoreUnavailable,
    TurnConflict,
    TurnOutOfOrder,
    create_orchestrator,
)
from callbot.engine.session import CallContext, SessionManager
from clinic_mock_sim import FakeClinicAPI, clinic_error

CANCEL_CALL = ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch", "Vâng", "Hủy giúp tôi"]


class SimulatedCrash(BaseException):
    """Worker chết giữa chừng: không phải Exception nên engine không bắt được."""


@pytest.fixture
def reopen(store) -> Iterator[Callable[[], object]]:
    """Một orchestrator khác dùng chung Redis session store."""
    yield lambda: store


def _outbound(call_id: str) -> CallStart:
    return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")


def _say(bot, call_id: str, turn: int, text):
    return bot.handle_turn(call_id, CallerInput(turn=turn, text=text))


def _context(store, call_id: str) -> CallContext:
    return CallContext.from_dict(store.get_session(call_id).context)


# --- Replay ----------------------------------------------------------------------------


def test_replay_only_while_active_and_never_reopens_purged_call(store) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=store)
    opening = bot.start_call(_outbound("c_replay"))
    results = []
    for turn, text in enumerate(CANCEL_CALL, 1):
        result = _say(bot, "c_replay", turn, text)
        results.append(result)
        if not result.ended:
            assert _say(bot, "c_replay", turn, text) == result
            assert bot.start_call(_outbound("c_replay")) == opening
    assert results[-1].outcome == "CANCELLED"

    before = store.get_session("c_replay")
    writes, requests = list(clinic.writes), list(clinic.requests)
    for turn, text in enumerate(CANCEL_CALL, 1):
        with pytest.raises(CallEnded):
            _say(bot, "c_replay", turn, text)
    with pytest.raises(CallEnded):
        bot.start_call(_outbound("c_replay"))

    after = store.get_session("c_replay")
    assert after == before  # history, bộ đếm, context không đổi
    assert clinic.writes == writes and clinic.requests == requests
    assert len(store.list_commands("c_replay")) == 1


def test_reopening_same_call_does_not_reset_context(store) -> None:
    bot = create_orchestrator(FakeClinicAPI(), store=store)
    opening = bot.start_call(_outbound("c_reopen"))
    _say(bot, "c_reopen", 1, "Nguyễn Văn A")
    assert bot.start_call(_outbound("c_reopen")) == opening
    ctx = _context(store, "c_reopen")
    assert ctx.claimed_name == "nguyễn văn a" and ctx.identity_step == "ASK_DOB"

    with pytest.raises(CallConflict):
        bot.start_call(CallStart(call_id="c_reopen", direction="outbound", appointment_id="apt_x"))


# --- Thứ tự ------------------------------------------------------------------------------


def test_order_errors_leave_session_unchanged(store) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=store)
    bot.start_call(_outbound("c_order"))
    _say(bot, "c_order", 1, "Nguyễn Văn A")
    before = store.get_session("c_order")

    with pytest.raises(TurnOutOfOrder) as skipped:
        _say(bot, "c_order", 3, "14/03/1978")
    assert skipped.value.expected_turn == 2
    with pytest.raises(TurnConflict):
        _say(bot, "c_order", 1, "Nguyễn Văn B")
    with pytest.raises(TurnConflict):
        # Giữ nguyên text: null khác chuỗi rỗng, không chuẩn hoá
        bot.handle_turn("c_order", CallerInput(turn=1, text="Nguyễn Văn A ", silence_ms=0))
    with pytest.raises(SessionNotFound):
        _say(bot, "c_missing", 1, "alo")

    assert store.get_session("c_order") == before
    assert store.get_turn("c_order", 3) is None


def test_all_turns_after_end_are_rejected(store) -> None:
    bot = create_orchestrator(FakeClinicAPI(), store=store)
    bot.start_call(_outbound("c_ended"))
    last = _say(bot, "c_ended", 1, "cho tôi gặp nhân viên")
    assert last.ended
    with pytest.raises(CallEnded):
        _say(bot, "c_ended", 2, "alo")
    with pytest.raises(CallEnded):
        _say(bot, "c_ended", 1, "cho tôi gặp nhân viên")


def test_silence_input_is_compared_exactly(store) -> None:
    bot = create_orchestrator(FakeClinicAPI(), store=store)
    bot.start_call(_outbound("c_silence_fp"))
    first = bot.handle_turn("c_silence_fp", CallerInput(turn=1, text=None, silence_ms=1500))
    assert bot.handle_turn("c_silence_fp", CallerInput(turn=1, text=None, silence_ms=1500)) == first
    with pytest.raises(TurnConflict):
        bot.handle_turn("c_silence_fp", CallerInput(turn=1, text=None, silence_ms=1600))


# --- Đồng thời và restart --------------------------------------------------------------


def _slow_clinic(delay: float) -> FakeClinicAPI:
    clinic = FakeClinicAPI()
    clinic.delay("get_appointment", delay)  # chờ thật: các test dưới cần hai luồng chồng lên nhau
    return clinic


def test_two_threads_same_turn_process_once(store, reopen) -> None:
    clinic = _slow_clinic(0.2)
    workers = [create_orchestrator(clinic, store=reopen()) for _ in range(2)]
    workers[0].start_call(_outbound("c_race"))
    _say(workers[0], "c_race", 1, "Nguyễn Văn A")
    _say(workers[1], "c_race", 2, "14/03/1978")

    results: list[object] = []

    def send(worker) -> None:
        try:
            results.append(_say(worker, "c_race", 3, "Có, tôi đến được"))
        except CallEnded as exc:
            results.append(exc)

    threads = [threading.Thread(target=send, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert sum(isinstance(result, CallEnded) for result in results) == 1
    assert [result.outcome for result in results if not isinstance(result, CallEnded)] == [
        "CONFIRMED"
    ]
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
    assert len(store.list_commands("c_race")) == 1


def test_busy_call_returns_call_busy_without_changes(store) -> None:
    clinic = _slow_clinic(0.6)
    slow = create_orchestrator(clinic, store=store)
    slow.start_call(_outbound("c_busy_turn"))
    _say(slow, "c_busy_turn", 1, "Nguyễn Văn A")
    impatient = create_orchestrator(clinic, store=store)
    impatient._sessions = SessionManager(store, lock_timeout_s=0.1)

    worker = threading.Thread(target=_say, args=(slow, "c_busy_turn", 2, "14/03/1978"))
    worker.start()
    time.sleep(0.2)
    with pytest.raises(CallBusy):
        _say(impatient, "c_busy_turn", 2, "14/03/1978")
    worker.join()
    assert store.get_session("c_busy_turn").last_completed_turn == 2


def test_different_calls_do_not_block_each_other(store) -> None:
    clinic = _slow_clinic(0.5)
    bot = create_orchestrator(clinic, store=store)
    for call_id in ("c_iso_1", "c_iso_2"):
        bot.start_call(_outbound(call_id))
        _say(bot, call_id, 1, "Nguyễn Văn A")
    quick = create_orchestrator(FakeClinicAPI(), store=store)
    quick._sessions = SessionManager(store, lock_timeout_s=0.1)

    worker = threading.Thread(target=_say, args=(bot, "c_iso_1", 2, "14/03/1978"))
    worker.start()
    time.sleep(0.1)
    assert _say(quick, "c_iso_2", 2, "gì cơ").state == "AWAITING_IDENTITY"
    worker.join()
    assert _context(store, "c_iso_1").identity_verified
    assert not _context(store, "c_iso_2").identity_verified


def test_orchestrators_in_same_process_share_active_session(store, reopen) -> None:
    clinic = FakeClinicAPI()
    before_restart = create_orchestrator(clinic, store=reopen())
    before_restart.start_call(_outbound("c_restart"))
    asked_dob = _say(before_restart, "c_restart", 1, "Nguyễn Văn A")

    after_restart = create_orchestrator(clinic, store=reopen())
    assert _say(after_restart, "c_restart", 1, "Nguyễn Văn A") == asked_dob
    summary = _say(after_restart, "c_restart", 2, "14/03/1978")
    assert summary.state == "AWAITING_INTENT"
    assert _say(after_restart, "c_restart", 3, "Có, tôi đến được").outcome == "CONFIRMED"


# --- Gián đoạn ---------------------------------------------------------------------------


def _verified(bot, call_id: str) -> None:
    bot.start_call(_outbound(call_id))
    _say(bot, call_id, 1, "Nguyễn Văn A")
    _say(bot, call_id, 2, "14/03/1978")


def test_crash_before_clinic_write_recovers_safely(store, reopen) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=reopen())
    _verified(bot, "c_crash_before")
    clinic.fail_next("get_appointment", SimulatedCrash())
    with pytest.raises(SimulatedCrash):
        _say(bot, "c_crash_before", 3, "Có, tôi đến được")
    assert store.get_turn("c_crash_before", 3).status == "PROCESSING"
    assert store.list_commands("c_crash_before") == [] and clinic.writes == []

    restarted = create_orchestrator(clinic, store=reopen())
    assert _say(restarted, "c_crash_before", 3, "Có, tôi đến được").outcome == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def test_crash_after_clinic_success_before_commit_blocks_for_reconciliation(store, reopen) -> None:
    clinic = FakeClinicAPI()
    crashing_store = reopen()
    bot = create_orchestrator(clinic, store=crashing_store)
    _verified(bot, "c_crash_mid")

    original = crashing_store.complete_turn

    def crash(*args, **kwargs):
        raise SimulatedCrash()

    crashing_store.complete_turn = crash
    try:
        with pytest.raises(SimulatedCrash):
            _say(bot, "c_crash_mid", 3, "Có, tôi đến được")
    finally:
        crashing_store.complete_turn = original
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
    [command] = store.list_commands("c_crash_mid")
    assert command.status == "SUCCEEDED"

    restarted = create_orchestrator(clinic, store=reopen())
    with pytest.raises(ReconciliationRequired):
        _say(restarted, "c_crash_mid", 3, "Có, tôi đến được")
    assert store.get_turn("c_crash_mid", 3).status == "RECONCILIATION_REQUIRED"
    with pytest.raises(ReconciliationRequired):
        _say(restarted, "c_crash_mid", 4, "alo")
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]  # không gửi lại, không chuyển máy


def test_lost_terminal_response_is_not_replayed_after_content_erasure(store) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=store)
    _verified(bot, "c_crash_after")
    lost = _say(bot, "c_crash_after", 3, "Có, tôi đến được")  # phản hồi không tới harness
    assert lost.outcome == "CONFIRMED"
    with pytest.raises(CallEnded):
        _say(bot, "c_crash_after", 3, "Có, tôi đến được")
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def test_write_timeout_requires_reconciliation_without_transfer(store) -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next(
        "confirm_appointment",
        httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://clinic.test")),
    )
    bot = create_orchestrator(clinic, store=store)
    _verified(bot, "c_timeout")
    with pytest.raises(ReconciliationRequired):
        _say(bot, "c_timeout", 3, "Có, tôi đến được")

    [command] = store.list_commands("c_timeout")
    assert command.status == "UNKNOWN" and command.idempotency_key == "c_timeout:3:confirm"
    assert clinic.writes == []  # không phát sinh lệnh chuyển máy thay thế
    assert [op for _, op in clinic.requests] == ["CONFIRMED"]
    with pytest.raises(ReconciliationRequired):
        _say(bot, "c_timeout", 3, "Có, tôi đến được")
    assert [op for _, op in clinic.requests] == ["CONFIRMED"]  # không gửi lại
    assert store.get_session("c_timeout").context == {}


def test_store_unavailable_before_journal_sends_nothing(store) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=store)
    _verified(bot, "c_redis_down")

    original = store.begin_command

    def unavailable(command):
        raise SessionStoreUnavailable("redis down")

    store.begin_command = unavailable
    try:
        with pytest.raises(SessionStoreUnavailable):
            _say(bot, "c_redis_down", 3, "Có, tôi đến được")
    finally:
        store.begin_command = original
    assert clinic.requests == [] and clinic.writes == []

    assert _say(bot, "c_redis_down", 3, "Có, tôi đến được").outcome == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def test_version_conflict_retries_once_with_same_key(store) -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    bot = create_orchestrator(clinic, store=store)
    _verified(bot, "c_conflict")
    assert _say(bot, "c_conflict", 3, "Có, tôi đến được").outcome == "CONFIRMED"
    keys = {key for key, _ in clinic.requests}
    assert keys == {"c_conflict:3:confirm"}
    [command] = store.list_commands("c_conflict")
    assert (command.status, command.attempts) == ("SUCCEEDED", 2)


def test_replayed_turn_returns_guarded_action_without_rerunning_guard(store, monkeypatch) -> None:
    """R-01: guard chạy trước commit; replay của phiên còn hoạt động trả lại action đã guard."""
    from callbot.engine.policy import output_guard

    checked = []
    check = output_guard.check

    def counting(inp):
        checked.append(inp.action.utterance)
        return check(inp)

    monkeypatch.setattr(output_guard, "check", counting)
    bot = create_orchestrator(FakeClinicAPI(), store=store)
    bot.start_call(_outbound("c_r01_replay"))
    first = _say(bot, "c_r01_replay", 1, "Nguyễn Văn A")
    assert not first.ended and checked == [first.utterance]

    again = _say(bot, "c_r01_replay", 1, "Nguyễn Văn A")
    assert again == first and checked == [first.utterance]
