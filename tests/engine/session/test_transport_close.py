"""R-36: khách rời cuộc gọi giữa chừng — không gửi thêm lệnh ghi nào, lệnh đã gửi giữ nguyên kết quả.

Mỗi test là một dòng của bảng 2.1 trong docs/plans/call-lifecycle-recovery-plan-2026-10-11.md.
"Khách rời giữa lượt" được giả bằng `request_call_close` gọi từ bên trong lời gọi Clinic của lượt đó
(cùng thread với lượt, đúng như callback LiveKit ghi yêu cầu đóng trong lúc Core đang chạy).
"""

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    create_orchestrator,
)
from clinic_mock_sim import FakeClinicAPI, clinic_error

CALL_ID = "c_hangup"
# Lượt cuối ("Hủy giúp tôi") gửi lệnh hủy (xem test_turn_lifecycle.CANCEL_CALL).
BEFORE_CANCEL = ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch", "Vâng"]
CANCEL_TURN = (5, "Hủy giúp tôi")


@pytest.fixture
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def bot(clinic, store):
    bot = create_orchestrator(clinic, store=store)
    bot.start_call(CallStart(call_id=CALL_ID, direction="outbound", appointment_id="apt_00417"))
    return bot


def _say(bot, turn: int, text: str):
    return bot.handle_turn(CALL_ID, CallerInput(turn=turn, text=text))


def _reach_cancel_turn(bot) -> None:
    for turn, text in enumerate(BEFORE_CANCEL, 1):
        assert not _say(bot, turn, text).ended


def _cancels(clinic) -> list:
    return [write for write in clinic.writes if write[1] == "CANCELLED"]


def _hang_up_during(monkeypatch, clinic, bot, operation: str, then=None) -> list[int]:
    """Lần gọi `operation` kế tiếp: khách rời cuộc gọi ngay lúc đó, rồi chạy `then` (mặc định gọi
    thật). Trả danh sách đếm số lần `operation` được gọi."""
    original = getattr(clinic, operation)
    calls: list[int] = []

    def hooked(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            bot.request_call_close(CALL_ID)
            if then is not None:
                return then()
        return original(*args, **kwargs)

    monkeypatch.setattr(clinic, operation, hooked)
    return calls


def test_hangup_before_the_write_is_sent_sends_nothing(monkeypatch, bot, clinic, store) -> None:
    _reach_cancel_turn(bot)
    # Đọc version ngay trước lệnh ghi: khách rời đúng lúc này, lệnh hủy chưa gửi
    _hang_up_during(monkeypatch, clinic, bot, "get_appointment")

    with pytest.raises(CallEnded):
        _say(bot, *CANCEL_TURN)

    assert _cancels(clinic) == []
    assert not any(write[1] == "TRANSFERRED" for write in clinic.writes)  # không chuyển máy bù
    assert [c.status for c in store.list_commands(CALL_ID)] == ["FAILED"]
    assert bot.close_call(CALL_ID) is True
    session = store.get_session(CALL_ID)
    assert (session.purged_reason, session.transport_closed) == ("HANGUP", True)
    assert session.context == {}  # dữ liệu khách đã xoá


def test_hangup_while_the_write_succeeds_keeps_the_result(monkeypatch, bot, clinic, store) -> None:
    _reach_cancel_turn(bot)
    _hang_up_during(monkeypatch, clinic, bot, "cancel_appointment")

    action = _say(bot, *CANCEL_TURN)  # lệnh đã gửi: Clinic trả 200, lượt chạy xong như thường

    assert action.outcome == "CANCELLED"
    assert len(_cancels(clinic)) == 1
    assert bot.close_call(CALL_ID) is True
    session = store.get_session(CALL_ID)
    # Kết quả đã ghi không bao giờ bị đổi thành HANGUP
    assert (session.purged_reason, session.transport_closed) == ("ENDED", True)


def test_hangup_after_an_unknown_send_is_not_resent(monkeypatch, bot, clinic, store) -> None:
    _reach_cancel_turn(bot)
    clinic_timeout = clinic_error(None, "TIMEOUT", outcome_known=False)

    def timeout():
        raise clinic_timeout

    calls = _hang_up_during(monkeypatch, clinic, bot, "cancel_appointment", then=timeout)

    with pytest.raises(ReconciliationRequired):
        _say(bot, *CANCEL_TURN)

    assert len(calls) == 1  # không gửi lại cùng key sau khi khách rời
    assert [c.status for c in store.list_commands(CALL_ID)] == ["UNKNOWN"]
    assert bot.close_call(CALL_ID) is True
    session = store.get_session(CALL_ID)
    assert (session.purged_reason, session.transport_closed) == ("RECONCILIATION_REQUIRED", True)


def test_hangup_with_a_version_conflict_does_not_reread_and_resend(
    monkeypatch, bot, clinic, store
) -> None:
    _reach_cancel_turn(bot)
    conflict = clinic_error(409, "VERSION_CONFLICT")

    def rejected():
        raise conflict

    calls = _hang_up_during(monkeypatch, clinic, bot, "cancel_appointment", then=rejected)

    with pytest.raises(CallEnded):
        _say(bot, *CANCEL_TURN)

    assert len(calls) == 1  # §4.2.5 bình thường gửi lại một lần — sau khi khách rời thì không
    assert _cancels(clinic) == []
    assert bot.close_call(CALL_ID) is True
    assert store.get_session(CALL_ID).purged_reason == "HANGUP"


def test_without_hangup_a_version_conflict_is_still_resent_once(monkeypatch, bot, clinic) -> None:
    """Cổng ghi không đổi hành vi khi khách còn trên máy."""
    _reach_cancel_turn(bot)
    clinic.fail_next("cancel_appointment", clinic_error(409, "VERSION_CONFLICT"))

    assert _say(bot, *CANCEL_TURN).outcome == "CANCELLED"
    assert len(_cancels(clinic)) == 1


def test_no_new_turn_or_reopen_after_hangup(bot, clinic, store) -> None:
    assert not _say(bot, 1, BEFORE_CANCEL[0]).ended
    requests = list(clinic.requests)

    bot.request_call_close(CALL_ID)

    with pytest.raises(CallEnded):
        _say(bot, 2, BEFORE_CANCEL[1])
    assert clinic.requests == requests  # lượt sau khi rời không chạm Clinic
    assert bot.close_call(CALL_ID) is True
    assert bot.close_call(CALL_ID) is False  # đóng lặp lại: không đổi gì
    with pytest.raises(CallEnded):
        bot.start_call(CallStart(call_id=CALL_ID, direction="outbound", appointment_id="apt_00417"))
    session = store.get_session(CALL_ID)
    assert (session.purged_reason, session.transport_closed) == ("HANGUP", True)


def test_closing_after_a_normal_end_keeps_the_business_outcome(bot, clinic, store) -> None:
    _reach_cancel_turn(bot)
    assert _say(bot, *CANCEL_TURN).outcome == "CANCELLED"

    assert bot.close_call(CALL_ID) is True
    assert store.get_session(CALL_ID).purged_reason == "ENDED"


def test_closing_an_unknown_call_is_a_no_op(clinic, store) -> None:
    bot = create_orchestrator(clinic, store=store)
    assert bot.close_call("c_never_opened") is False
