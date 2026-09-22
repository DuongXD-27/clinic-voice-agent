"""Lỗi kết thúc cuộc gọi: lifecycle lịch hẹn, ghi trạng thái kết thúc, lưu lỗi vào phiên và chẩn đoán.

Không lỗi nào được báo thành công giả: không TRANSFERRED khi /transfer không thành công, không
UNREACHABLE khi /unreachable bị từ chối, và lỗi lifecycle không chuyển thành một lần gọi /transfer.
"""

import json
from typing import Any, Optional

import pytest

from callbot.engine import (
    AppointmentNotActionable,
    CallerInput,
    CallStart,
    ClinicInvalidResponse,
    ClinicTerminationFailed,
    ReconciliationRequired,
    SessionStoreUnavailable,
    create_orchestrator,
)
from callbot.engine.errors import CallTerminated
from tests.engine.fake_clinic import FakeClinicAPI, clinic_error

NAME, DOB = "Nguyễn Văn A", "14/03/1978"
SILENCE = None


def _caller(turn: int, line: Optional[str]) -> CallerInput:
    if line is SILENCE:
        return CallerInput(turn=turn, text=None, silence_ms=2000)
    return CallerInput(turn=turn, text=line)


def _bot(call_id: str, clinic: Optional[FakeClinicAPI] = None, direction: str = "outbound"):
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    if direction == "outbound":
        call = CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")
    else:
        call = CallStart(call_id=call_id, direction="inbound", caller_number="0912345600")
    bot.start_call(call)
    return bot, clinic, call


def _run(bot, call_id: str, lines: list[Optional[str]], start: int = 1):
    actions = [
        bot.handle_turn(call_id, _caller(turn, line)) for turn, line in enumerate(lines, start)
    ]
    return actions[-1]


def _raw_state(bot, call_id: str) -> str:
    store = bot.sessions.store
    return store._client.get(store._state_key(call_id))


def _set_status(clinic: FakeClinicAPI, status: str) -> None:
    clinic.appointments["apt_00417"]["status"] = status


# --- Mở cuộc gọi --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["CANCELLED", "RESCHEDULED", "TRANSFERRED", "UNREACHABLE"])
def test_opening_a_call_on_a_non_actionable_appointment_creates_no_session(status: str) -> None:
    clinic = FakeClinicAPI()
    _set_status(clinic, status)
    bot = create_orchestrator(clinic)
    call = CallStart(call_id="c_open_blocked", direction="outbound", appointment_id="apt_00417")
    with pytest.raises(AppointmentNotActionable):
        bot.start_call(call)
    assert bot.sessions.store.get_session("c_open_blocked") is None
    assert clinic.requests == []


@pytest.mark.parametrize("status", ["SCHEDULED", "BOOKED", "CONFIRMED"])
def test_actionable_appointments_open_normally(status: str) -> None:
    clinic = FakeClinicAPI()
    _set_status(clinic, status)
    bot, _, _ = _bot("c_open_ok", clinic)
    assert bot.sessions.store.get_session("c_open_ok").context != {}


def test_opening_on_an_invalid_read_creates_no_session() -> None:
    clinic = FakeClinicAPI()
    del clinic.appointments["apt_00417"]["starts_at"]
    bot = create_orchestrator(clinic)
    call = CallStart(call_id="c_open_invalid", direction="outbound", appointment_id="apt_00417")
    with pytest.raises(ClinicInvalidResponse):
        bot.start_call(call)
    assert bot.sessions.store.get_session("c_open_invalid") is None


# --- Lịch đổi trạng thái giữa cuộc gọi ------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "line"),
    [
        ([NAME], DOB),  # đọc lại lịch sau xác minh, trước khi đọc tóm tắt
        ([NAME, DOB], "Vâng"),  # trước lệnh ghi CONFIRMED
        ([NAME, DOB], "để tôi xem đã"),  # trước khi đọc lại lịch để hỏi lại
        ([NAME, DOB, "Không"], "tôi sẽ đến"),  # trước khi đọc lại lịch để mời xác nhận
        ([NAME, DOB, "Tôi muốn hủy lịch"], "Hủy giúp tôi"),  # trước lệnh ghi CANCELLED
        ([NAME, DOB, "Tôi muốn hủy lịch"], "Thôi không hủy nữa"),  # trước khi đọc lại để giữ lịch
    ],
    ids=["after_verify", "before_confirm", "reread", "readback", "before_cancel", "keep"],
)
def test_appointment_cancelled_elsewhere_mid_call_stops_without_any_write(
    before: list[str], line: str
) -> None:
    bot, clinic, _ = _bot("c_mid_call")
    _run(bot, "c_mid_call", before)
    _set_status(clinic, "CANCELLED")
    writes_before = len(clinic.requests)

    with pytest.raises(AppointmentNotActionable):
        bot.handle_turn("c_mid_call", _caller(len(before) + 1, line))

    # Không lệnh ghi nào sau từ chối lifecycle, kể cả /transfer
    assert len(clinic.requests) == writes_before == 0
    session = bot.sessions.store.get_session("c_mid_call")
    assert session.purged_reason == "FAILED" and session.ended
    assert session.failure["code"] == "APPOINTMENT_NOT_ACTIONABLE"
    assert session.failure["http_status"] == 409


# --- Phiên đã dừng vì lỗi: không xử lý lại ---------------------------------------------------------


def _failed_call(call_id: str):
    bot, clinic, call = _bot(call_id)
    _run(bot, call_id, [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    with pytest.raises(AppointmentNotActionable) as exc:
        bot.handle_turn_with_details(call_id, _caller(3, "Vâng"))
    return bot, clinic, call, exc.value


def test_a_failed_call_keeps_the_extraction_in_its_diagnostics() -> None:
    _, _, _, error = _failed_call("c_failed_diag")
    diagnostics = error.diagnostics
    assert diagnostics is not None
    assert (diagnostics.question_id, diagnostics.extraction_source) == ("CONFIRM_READBACK", "RULE")
    assert (diagnostics.error_type, diagnostics.error_code) == (
        "APPOINTMENT_NOT_ACTIONABLE",
        "INVALID_STATE_TRANSITION",
    )
    assert diagnostics.transfer_reason is None


def test_resending_to_a_failed_call_replays_the_error_without_processing() -> None:
    bot, clinic, call, _ = _failed_call("c_failed_replay")
    calls_before = len(clinic.calls)
    for attempt in (
        lambda: bot.handle_turn("c_failed_replay", _caller(3, "Vâng")),  # gửi lại cùng lượt
        lambda: bot.handle_turn("c_failed_replay", _caller(4, "Vâng")),  # lượt tiếp theo
        lambda: bot.start_call(call),  # mở lại cùng call_id
    ):
        with pytest.raises(AppointmentNotActionable) as exc:
            attempt()
        assert exc.value.diagnostics.question_id == "CONFIRM_READBACK"
    # Không extract lại, không gọi Clinic lại
    assert len(clinic.calls) == calls_before


def test_a_failed_call_keeps_only_the_technical_tombstone() -> None:
    bot, _, _, _ = _failed_call("c_failed_pii")
    raw = _raw_state(bot, "c_failed_pii")
    state = json.loads(raw)
    assert NAME not in raw and "Vâng" not in raw and "1978" not in raw
    assert state["session"]["context"] == {} and state["session"]["start_config"] == {}
    assert state["turns"]["3"]["status"] == "FAILED" and state["turns"]["3"]["input"] == {}
    assert set(state["session"]["failure"]) == {"http_status", "code", "diagnostics"}
    # Tombstone dùng TTL hiện có
    ttl = bot.sessions.store._client.ttl(bot.sessions.store._state_key("c_failed_pii"))
    assert 0 < ttl <= bot.sessions.store._tombstone_ttl_s


def test_failure_that_cannot_be_saved_surfaces_the_store_error(monkeypatch) -> None:
    bot, clinic, _ = _bot("c_failed_store")
    _run(bot, "c_failed_store", [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise SessionStoreUnavailable("down")

    monkeypatch.setattr(bot.sessions.store, "fail_turn", unavailable)
    with pytest.raises(SessionStoreUnavailable) as exc:
        bot.handle_turn("c_failed_store", _caller(3, "Vâng"))
    assert exc.value.diagnostics.error_type == "APPOINTMENT_NOT_ACTIONABLE"
    assert clinic.writes == []


def test_sessions_saved_before_the_failure_field_still_load() -> None:
    bot, _, _ = _bot("c_old_record")
    store = bot.sessions.store
    state = json.loads(_raw_state(bot, "c_old_record"))
    state["session"].pop("failure")
    store._client.set(store._state_key("c_old_record"), json.dumps(state, ensure_ascii=False))

    assert store.get_session("c_old_record").failure is None
    action = _run(bot, "c_old_record", [NAME])
    assert not action.ended


def test_restored_failures_drop_unknown_codes() -> None:
    error = CallTerminated.restore(
        {
            "http_status": 409,
            "code": "APPOINTMENT_NOT_ACTIONABLE",
            "diagnostics": {
                "question_id": "Nguyễn Văn A",
                "extraction_source": "RULE",
                "error_code": "secret",
            },
        }
    )
    assert isinstance(error, AppointmentNotActionable)
    assert error.diagnostics.question_id is None and error.diagnostics.error_code == "UNKNOWN"


# --- Ghi trạng thái kết thúc --------------------------------------------------------------------


def test_transfer_reports_transferred_only_after_clinic_records_it() -> None:
    bot, clinic, _ = _bot("c_transfer_ok")
    run = bot.handle_turn_with_details("c_transfer_ok", _caller(1, "cho tôi gặp nhân viên"))
    assert (run.action.outcome, run.action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]
    assert run.diagnostics.transfer_reason == "PATIENT_REQUEST"


@pytest.mark.parametrize(
    "error",
    [clinic_error(422, "IDEMPOTENCY_CONFLICT"), clinic_error(404, "NOT_FOUND")],
    ids=["idempotency", "not_found"],
)
def test_rejected_transfer_is_a_termination_failure(error) -> None:
    bot, clinic, _ = _bot("c_transfer_rejected")
    clinic.fail_next("transfer_appointment", error)
    with pytest.raises(ClinicTerminationFailed) as exc:
        bot.handle_turn("c_transfer_rejected", _caller(1, "cho tôi gặp nhân viên"))
    assert exc.value.diagnostics.transfer_reason == "PATIENT_REQUEST"
    assert exc.value.diagnostics.error_code == error.code
    assert clinic.writes == []


def test_invalid_state_on_transfer_is_not_actionable() -> None:
    bot, clinic, _ = _bot("c_transfer_state")
    clinic.fail_next("transfer_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    with pytest.raises(AppointmentNotActionable):
        bot.handle_turn("c_transfer_state", _caller(1, "cho tôi gặp nhân viên"))
    assert [op for _, op in clinic.requests].count("TRANSFERRED") == 1


def test_transfer_timeout_needs_reconciliation() -> None:
    bot, clinic, _ = _bot("c_transfer_timeout")
    clinic.fail_next("transfer_appointment", outcome_unknown=True)
    with pytest.raises(ReconciliationRequired) as exc:
        bot.handle_turn("c_transfer_timeout", _caller(1, "cho tôi gặp nhân viên"))
    assert exc.value.diagnostics.transfer_reason == "PATIENT_REQUEST"


@pytest.mark.parametrize(
    ("operation", "lines"),
    [
        ("transfer_appointment", ["cho tôi gặp nhân viên"]),
        ("mark_unreachable", [SILENCE, SILENCE, SILENCE]),
    ],
)
def test_a_2xx_with_the_wrong_status_needs_reconciliation(operation: str, lines) -> None:
    bot, clinic, _ = _bot("c_wrong_status")
    setattr(clinic, operation, lambda *a, **k: {**clinic.appointments["apt_00417"]})
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_wrong_status", lines)


def test_a_business_write_error_transfers_only_when_the_transfer_succeeds() -> None:
    """Confirm bị từ chối -> SYSTEM_ERROR; /transfer cũng bị từ chối -> lỗi kết thúc, không TRANSFERRED."""
    bot, clinic, _ = _bot("c_double_reject")
    _run(bot, "c_double_reject", [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    clinic.fail_next("transfer_appointment", clinic_error(429, "RATE_LIMITED"))
    with pytest.raises(ClinicTerminationFailed) as exc:
        bot.handle_turn("c_double_reject", _caller(3, "Vâng"))
    diagnostics = exc.value.diagnostics
    assert diagnostics.transfer_reason == "SYSTEM_ERROR"
    assert diagnostics.question_id == "CONFIRM_READBACK"
    assert (diagnostics.error_type, diagnostics.error_code) == (
        "CLINIC_TERMINATION_FAILED",
        "RATE_LIMITED",
    )
    assert clinic.writes == []


def test_a_handled_write_error_is_visible_in_the_turn_diagnostics() -> None:
    bot, clinic, _ = _bot("c_handled")
    _run(bot, "c_handled", [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    run = bot.handle_turn_with_details("c_handled", _caller(3, "Vâng"))
    assert run.action.outcome == "TRANSFERRED"
    assert (run.diagnostics.error_type, run.diagnostics.error_code) == (
        "CLINIC_REJECTED",
        "IDEMPOTENCY_CONFLICT",
    )
    assert run.diagnostics.question_id == "CONFIRM_READBACK"


def test_inbound_transfer_without_a_booking_still_needs_no_clinic_write() -> None:
    bot, clinic, _ = _bot("c_inbound_transfer", direction="inbound")
    action = _run(bot, "c_inbound_transfer", ["cho tôi gặp nhân viên"])
    assert action.outcome == "TRANSFERRED" and clinic.requests == []
