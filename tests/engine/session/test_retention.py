from datetime import datetime, timedelta, timezone

import pytest

from callbot.engine.errors import ReconciliationRequired, SessionStoreUnavailable
from callbot.engine.session.retention import RetentionPolicy
from callbot.engine.session.store import CommandRecord, SessionRecord

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


def _session(call_id: str) -> SessionRecord:
    return SessionRecord(
        call_id=call_id,
        start_config={"call_id": call_id, "caller_number": "0900000000"},
        opening={"utterance": "Xin chào", "state": "AWAITING_IDENTITY"},
        context={"state": "AWAITING_IDENTITY", "full_name": "Nguyễn Văn A"},
    )


def _seed(store, call_id: str = "c_retention") -> None:
    store.create_session(_session(call_id))
    store.reserve_turn(
        call_id,
        1,
        {"text": "Tôi muốn đặt lịch", "audio_url": None, "silence_ms": 0},
        NOW,
    )


def _command(call_id: str) -> CommandRecord:
    return CommandRecord(
        idempotency_key=f"{call_id}:1:book",
        call_id=call_id,
        turn=1,
        operation="book",
        endpoint="/appointments",
        payload={"patient_name": "Nguyễn Văn A"},
        if_match=None,
    )


def _assert_customer_content_removed(store, call_id: str) -> None:
    session = store.get_session(call_id)
    assert session is not None
    assert session.start_config == {}
    assert session.opening == {}
    assert session.context == {}
    turn = store.get_turn(call_id, 1)
    assert turn is not None
    assert turn.input == {}
    assert turn.result in (None, {})
    assert turn.extraction is None
    for command in store.list_commands(call_id):
        assert command.endpoint == ""
        assert command.payload == {}
        assert command.result is None
        assert command.error is None


def test_active_session_has_ttl_and_is_bounded(redis_store_factory) -> None:
    store = redis_store_factory(
        retention=RetentionPolicy(idle_seconds=10, max_age_seconds=30),
        max_session_bytes=4096,
    )
    _seed(store)

    ttl = store._client.ttl(store._state_key("c_retention"))
    assert 0 < ttl <= 10

    with pytest.raises(SessionStoreUnavailable, match="4096"):
        store.complete_turn(
            "c_retention",
            1,
            {"large": "x" * 5000},
            {"utterance": "ok"},
            None,
            ended=False,
        )
    assert store.get_session("c_retention").last_completed_turn == 0


@pytest.mark.parametrize(
    ("status", "reason"),
    [("SUCCEEDED", "CLINIC_COMMITTED"), ("UNKNOWN", "RECONCILIATION_REQUIRED")],
)
def test_clinic_write_outcome_removes_customer_content(
    redis_store_factory, status: str, reason: str
) -> None:
    store = redis_store_factory()
    call_id = f"c_{status.lower()}"
    _seed(store, call_id)
    command = _command(call_id)
    store.begin_command(command)

    store.finish_command(
        call_id,
        command.idempotency_key,
        status,
        result={"appointment_id": "apt_private"},
        error="private upstream detail",
    )

    assert store.get_session(call_id).purged_reason == reason
    _assert_customer_content_removed(store, call_id)
    with pytest.raises(ReconciliationRequired):
        store.begin_command(command)


def test_terminal_turn_removes_customer_content(redis_store_factory) -> None:
    store = redis_store_factory()
    _seed(store, "c_end")
    store.complete_turn(
        "c_end",
        1,
        {"state": "ENDED", "full_name": "Nguyễn Văn A"},
        {"utterance": "Tạm biệt", "ended": True},
        {"full_name": "Nguyễn Văn A"},
        ended=True,
    )

    assert store.get_session("c_end").purged_reason == "ENDED"
    _assert_customer_content_removed(store, "c_end")


def test_successful_clinic_write_can_finish_terminal_turn(redis_store_factory) -> None:
    store = redis_store_factory()
    _seed(store, "c_commit")
    command = _command("c_commit")
    store.begin_command(command)
    store.finish_command("c_commit", command.idempotency_key, "SUCCEEDED", result={"ok": True})

    store.complete_turn(
        "c_commit",
        1,
        {"state": "ENDED"},
        {"utterance": "Đã ghi nhận"},
        None,
        ended=True,
    )

    session = store.get_session("c_commit")
    assert (session.last_completed_turn, session.purged_reason) == (1, "ENDED")
    assert store.get_turn("c_commit", 1).status == "COMPLETED"
    _assert_customer_content_removed(store, "c_commit")


def test_expired_session_is_scrubbed_and_tombstone_retained(redis_store_factory) -> None:
    clock = [NOW]
    store = redis_store_factory(
        retention=RetentionPolicy(idle_seconds=10, max_age_seconds=30),
        tombstone_ttl_s=60,
        clock=lambda: clock[0],
    )
    _seed(store, "c_expired")

    clock[0] += timedelta(seconds=10)
    assert store.purge_expired() == 1
    assert store.get_session("c_expired").purged_reason == "EXPIRED"
    _assert_customer_content_removed(store, "c_expired")
    assert 0 < store._client.ttl(store._state_key("c_expired")) <= 60


def test_maximum_age_expires_even_after_recent_activity(redis_store_factory) -> None:
    clock = [NOW]
    store = redis_store_factory(
        retention=RetentionPolicy(idle_seconds=20, max_age_seconds=30),
        clock=lambda: clock[0],
    )
    _seed(store, "c_max_age")
    clock[0] += timedelta(seconds=19)
    store.complete_turn(
        "c_max_age", 1, {"state": "ACTIVE"}, {"utterance": "tiếp"}, None, ended=False
    )
    clock[0] += timedelta(seconds=11)

    store.expire_session("c_max_age")

    assert store.get_session("c_max_age").purged_reason == "EXPIRED"


def test_pending_command_expires_into_reconciliation_tombstone(redis_store_factory) -> None:
    clock = [NOW]
    store = redis_store_factory(
        retention=RetentionPolicy(idle_seconds=10, max_age_seconds=30),
        clock=lambda: clock[0],
    )
    _seed(store, "c_pending")
    store.begin_command(_command("c_pending"))
    clock[0] += timedelta(seconds=10)

    store.expire_session("c_pending")

    assert store.get_session("c_pending").purged_reason == "RECONCILIATION_REQUIRED"
    assert store.find_blocked_turn("c_pending") is None
    _assert_customer_content_removed(store, "c_pending")


def test_cleanup_skips_a_call_while_another_worker_holds_its_lock(redis_store_factory) -> None:
    clock = [NOW]
    store = redis_store_factory(
        retention=RetentionPolicy(idle_seconds=10, max_age_seconds=30),
        clock=lambda: clock[0],
    )
    _seed(store, "c_locked")
    clock[0] += timedelta(seconds=10)

    with store.call_lock("c_locked", 1):
        assert store.purge_expired() == 0
        assert store.get_session("c_locked").purged_reason is None

    assert store.purge_expired() == 1


def test_redis_disconnect_fails_closed(redis_store_factory, redis_server) -> None:
    store = redis_store_factory()
    _seed(store, "c_down")
    redis_server.connected = False

    with pytest.raises(SessionStoreUnavailable):
        store.get_session("c_down")
    with pytest.raises(SessionStoreUnavailable):
        with store.call_lock("c_down", 0.1):
            pass


def test_lock_owner_change_is_reported(redis_store_factory) -> None:
    store = redis_store_factory(lock_lease_s=15)
    with pytest.raises(SessionStoreUnavailable, match="Mất khóa"):
        with store.call_lock("c_stolen", 0.1):
            store._client.set(store._lock_key("c_stolen"), "other-owner", px=1000)


def test_stale_lock_owner_cannot_overwrite_session(redis_store_factory) -> None:
    store = redis_store_factory(lock_lease_s=15)
    store.create_session(_session("c_fenced"))
    with pytest.raises(SessionStoreUnavailable, match="Mất khóa"):
        with store.call_lock("c_fenced", 0.1):
            store._client.set(store._lock_key("c_fenced"), "new-owner", px=1000)
            store.reserve_turn("c_fenced", 1, {"text": "private"}, NOW)
    assert store.get_turn("c_fenced", 1) is None


def test_server_config_accepts_only_ephemeral_bounded_noeviction(redis_store_factory) -> None:
    store = redis_store_factory()
    store._client.config_get = lambda *args: {
        "save": "",
        "appendonly": "no",
        "maxmemory": "268435456",
        "maxmemory-policy": "noeviction",
    }
    store.validate_server_config()

    store._client.config_get = lambda *args: {
        "save": "3600 1",
        "appendonly": "yes",
        "maxmemory": "0",
        "maxmemory-policy": "allkeys-lru",
    }
    with pytest.raises(SessionStoreUnavailable, match="save must be empty"):
        store.validate_server_config()
