"""Hợp đồng session store — chạy cho cả in-memory và PostgreSQL thật (fixture `store`)."""

import threading
import time
from datetime import datetime

import pytest

from callbot.engine.errors import CallBusy, ReconciliationRequired
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.session.store import CommandRecord, SessionRecord

RECEIVED = datetime(2026, 10, 12, 9, 0, 5, tzinfo=VN_TZ)


def _session(call_id: str) -> SessionRecord:
    return SessionRecord(
        call_id=call_id,
        start_config={"call_id": call_id, "direction": "outbound"},
        opening={"utterance": "Xin chào", "state": "AWAITING_IDENTITY"},
        context={"schema_version": 1, "state": "AWAITING_IDENTITY", "history": []},
    )


def _command(call_id: str, turn: int = 1, key: str = "k1", payload=None) -> CommandRecord:
    return CommandRecord(
        idempotency_key=key,
        call_id=call_id,
        turn=turn,
        operation="confirm",
        endpoint="/appointments/apt_00417/confirm",
        payload=payload or {},
        if_match=3,
    )


def test_session_and_turn_roundtrip(store) -> None:
    store.create_session(_session("c_rt"))
    assert store.get_session("c_rt") == _session("c_rt")
    assert store.get_session("c_missing") is None

    store.reserve_turn(
        "c_rt", 1, {"text": "Nguyễn Văn A", "silence_ms": 0, "audio_url": None}, RECEIVED
    )
    turn = store.get_turn("c_rt", 1)
    assert turn.status == "PROCESSING" and turn.received_at == RECEIVED
    assert turn.input["text"] == "Nguyễn Văn A"

    store.complete_turn(
        "c_rt",
        1,
        {"schema_version": 1, "state": "AWAITING_IDENTITY", "history": [{"turn": 1}]},
        {"utterance": "ngày sinh?", "state": "AWAITING_IDENTITY"},
        {"intent": {"value": "NONE", "provenance": "NONE", "span": None}},
        ended=False,
    )
    session = store.get_session("c_rt")
    assert session.last_completed_turn == 1 and session.context["history"] == [{"turn": 1}]
    completed = store.get_turn("c_rt", 1)
    assert completed.status == "COMPLETED" and completed.result["utterance"] == "ngày sinh?"
    assert completed.extraction["intent"]["provenance"] == "NONE"


def test_complete_turn_is_atomic_and_ordered(store) -> None:
    store.create_session(_session("c_atomic"))
    store.reserve_turn("c_atomic", 1, {}, RECEIVED)
    store.reserve_turn("c_atomic", 2, {}, RECEIVED)
    with pytest.raises(ValueError):
        store.complete_turn("c_atomic", 2, {"x": 1}, {"u": 1}, None, ended=False)
    # Không đổi gì khi lượt 2 commit sai thứ tự
    assert store.get_turn("c_atomic", 2).status == "PROCESSING"
    assert store.get_session("c_atomic").last_completed_turn == 0


def test_returned_records_are_copies(store) -> None:
    store.create_session(_session("c_copy"))
    loaded = store.get_session("c_copy")
    loaded.context["state"] = "ENDED"
    assert store.get_session("c_copy").context["state"] == "AWAITING_IDENTITY"


def test_reconciliation_flag(store) -> None:
    store.create_session(_session("c_block"))
    store.reserve_turn("c_block", 1, {}, RECEIVED)
    assert store.find_blocked_turn("c_block") is None
    store.mark_reconciliation_required("c_block", 1, "timeout confirm")
    assert store.find_blocked_turn("c_block") == 1
    assert store.get_turn("c_block", 1).detail == "timeout confirm"


def test_command_journal_lifecycle(store) -> None:
    store.create_session(_session("c_cmd"))
    store.reserve_turn("c_cmd", 1, {}, RECEIVED)
    store.begin_command(_command("c_cmd"))
    [pending] = store.list_commands("c_cmd", 1)
    assert (pending.status, pending.attempts, pending.if_match) == ("PENDING", 1, 3)

    # Chưa rõ kết quả: không được bắt đầu lại cùng khóa
    with pytest.raises(ReconciliationRequired):
        store.begin_command(_command("c_cmd"))

    store.finish_command("k1", "FAILED", error="HTTP 409 VERSION_CONFLICT")
    store.begin_command(_command("c_cmd"))  # lần trước thất bại xác định: gửi lại cùng khóa
    store.finish_command("k1", "SUCCEEDED", result={"status": "CONFIRMED"})
    [done] = store.list_commands("c_cmd")
    assert (done.status, done.attempts, done.result) == ("SUCCEEDED", 2, {"status": "CONFIRMED"})

    with pytest.raises(ReconciliationRequired):
        store.begin_command(_command("c_cmd"))  # đã thành công


def test_failed_command_key_cannot_be_reused_with_other_payload(store) -> None:
    store.create_session(_session("c_payload"))
    store.reserve_turn("c_payload", 1, {}, RECEIVED)
    store.begin_command(_command("c_payload", payload={"cancel_reason": "COST"}))
    store.finish_command("k1", "FAILED", error="HTTP 409")
    with pytest.raises(ReconciliationRequired):
        store.begin_command(_command("c_payload", payload={"cancel_reason": "UNSPECIFIED"}))


def test_lock_times_out_with_call_busy_and_other_calls_are_independent(store) -> None:
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with store.call_lock("c_busy", 5.0):
            holding.set()
            release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert holding.wait(5)
        started = time.monotonic()
        with pytest.raises(CallBusy):
            with store.call_lock("c_busy", 0.3):
                pass
        assert time.monotonic() - started >= 0.25
        with store.call_lock("c_other", 0.3):  # cuộc gọi khác không bị chặn
            pass
    finally:
        release.set()
        worker.join()

    with store.call_lock("c_busy", 1.0):  # khóa đã được nhả
        pass


def test_lock_released_when_body_raises(store) -> None:
    with pytest.raises(RuntimeError):
        with store.call_lock("c_raise", 1.0):
            raise RuntimeError("boom")
    with store.call_lock("c_raise", 0.5):
        pass


def test_ready(store) -> None:
    store.check_ready()
