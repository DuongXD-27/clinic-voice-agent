"""Clinic lỗi hoặc lịch không còn thao tác được: cuộc gọi luôn chuyển cho nhân viên.

Không báo thành công giả cho lệnh nghiệp vụ (CONFIRMED / CANCELLED / UNREACHABLE). Khi chính lệnh ghi
TRANSFERRED thất bại, bot vẫn trả TRANSFERRED để nhân viên xử lý; chỉ lệnh ghi chưa rõ kết quả mới
chặn lượt để đối soát.
"""

from typing import Optional

import pytest

from callbot.engine import (
    CallerInput,
    CallStart,
    ReconciliationRequired,
    create_orchestrator,
)
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


def _set_status(clinic: FakeClinicAPI, status: str) -> None:
    clinic.appointments["apt_00417"]["status"] = status


def _transferred(action, reason: str = "SYSTEM_ERROR") -> None:
    assert action.ended
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)


# --- Mở cuộc gọi --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["CANCELLED", "RESCHEDULED", "TRANSFERRED", "UNREACHABLE"])
def test_non_actionable_appointment_is_transferred_at_turn_one(status: str) -> None:
    clinic = FakeClinicAPI()
    _set_status(clinic, status)
    bot, _, _ = _bot("c_open_blocked", clinic)

    _transferred(_run(bot, "c_open_blocked", [NAME]))
    # Clinic không cho /transfer từ trạng thái này: không gửi lệnh ghi nào
    assert clinic.requests == []


@pytest.mark.parametrize("status", ["SCHEDULED", "BOOKED", "CONFIRMED"])
def test_actionable_appointments_open_normally(status: str) -> None:
    clinic = FakeClinicAPI()
    _set_status(clinic, status)
    bot, _, _ = _bot("c_open_ok", clinic)
    assert not _run(bot, "c_open_ok", [NAME]).ended


def test_invalid_read_at_opening_is_transferred_at_turn_one() -> None:
    clinic = FakeClinicAPI()
    del clinic.appointments["apt_00417"]["starts_at"]
    bot, _, _ = _bot("c_open_invalid", clinic)

    run = bot.handle_turn_with_details("c_open_invalid", _caller(1, NAME))
    _transferred(run.action)
    assert clinic.requests == []


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
def test_appointment_cancelled_elsewhere_mid_call_is_transferred_without_any_write(
    before: list[str], line: str
) -> None:
    bot, clinic, _ = _bot("c_mid_call")
    _run(bot, "c_mid_call", before)
    _set_status(clinic, "CANCELLED")

    run = bot.handle_turn_with_details("c_mid_call", _caller(len(before) + 1, line))

    _transferred(run.action)
    assert clinic.requests == []
    assert run.diagnostics.error_type == "APPOINTMENT_NOT_ACTIONABLE"


def test_invalid_state_on_a_business_write_is_transferred() -> None:
    bot, clinic, _ = _bot("c_confirm_state")
    _run(bot, "c_confirm_state", [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))

    run = bot.handle_turn_with_details("c_confirm_state", _caller(3, "Vâng"))

    _transferred(run.action)
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]
    assert (run.diagnostics.question_id, run.diagnostics.extraction_source) == (
        "CONFIRM_READBACK",
        "RULE",
    )
    assert (run.diagnostics.error_type, run.diagnostics.error_code) == (
        "APPOINTMENT_NOT_ACTIONABLE",
        "INVALID_STATE_TRANSITION",
    )


# --- Ghi trạng thái kết thúc --------------------------------------------------------------------


def test_transfer_is_recorded_on_clinic_when_it_can_be() -> None:
    bot, clinic, _ = _bot("c_transfer_ok")
    run = bot.handle_turn_with_details("c_transfer_ok", _caller(1, "cho tôi gặp nhân viên"))
    _transferred(run.action, "PATIENT_REQUEST")
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]
    assert run.diagnostics.transfer_reason == "PATIENT_REQUEST"


@pytest.mark.parametrize(
    "error",
    [
        clinic_error(422, "IDEMPOTENCY_CONFLICT"),
        clinic_error(404, "NOT_FOUND"),
        clinic_error(409, "INVALID_STATE_TRANSITION"),
        clinic_error(503, "UPSTREAM"),
    ],
    ids=["idempotency", "not_found", "invalid_state", "upstream"],
)
def test_rejected_transfer_still_hands_the_call_to_staff(error) -> None:
    bot, clinic, _ = _bot("c_transfer_rejected")
    clinic.fail_next("transfer_appointment", error)

    action = bot.handle_turn("c_transfer_rejected", _caller(1, "cho tôi gặp nhân viên"))

    _transferred(action, "PATIENT_REQUEST")
    assert clinic.writes == []


def test_unreadable_clinic_still_hands_the_call_to_staff() -> None:
    bot, clinic, _ = _bot("c_transfer_down")
    _run(bot, "c_transfer_down", [NAME])
    clinic.fail_next("get_appointment", clinic_error(None, "CONNECT_ERROR"))

    action = bot.handle_turn("c_transfer_down", _caller(2, "cho tôi gặp nhân viên"))

    _transferred(action, "PATIENT_REQUEST")
    assert clinic.requests == []


def test_rejected_unreachable_transfers_instead() -> None:
    """Clinic chỉ cho /unreachable từ SCHEDULED/BOOKED: lịch CONFIRMED thì ghi /transfer thay thế."""
    clinic = FakeClinicAPI()
    _set_status(clinic, "CONFIRMED")
    bot, _, _ = _bot("c_unreachable_rejected", clinic)

    action = _run(bot, "c_unreachable_rejected", [SILENCE, SILENCE, SILENCE])

    _transferred(action)
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_rejected_unreachable_and_transfer_still_hands_the_call_to_staff() -> None:
    bot, clinic, _ = _bot("c_unreachable_double")
    clinic.fail_next("mark_unreachable", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    clinic.fail_next("transfer_appointment", clinic_error(429, "RATE_LIMITED"))

    action = _run(bot, "c_unreachable_double", [SILENCE, SILENCE, SILENCE])

    _transferred(action)
    assert clinic.writes == []


def test_a_business_write_error_is_transferred_even_when_the_transfer_is_rejected() -> None:
    bot, clinic, _ = _bot("c_double_reject")
    _run(bot, "c_double_reject", [NAME, DOB])
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    clinic.fail_next("transfer_appointment", clinic_error(429, "RATE_LIMITED"))

    run = bot.handle_turn_with_details("c_double_reject", _caller(3, "Vâng"))

    _transferred(run.action)
    assert clinic.writes == []
    # Chẩn đoán giữ lỗi gốc của lượt (lệnh xác nhận bị từ chối)
    assert (run.diagnostics.error_type, run.diagnostics.error_code) == (
        "CLINIC_REJECTED",
        "IDEMPOTENCY_CONFLICT",
    )
    assert run.diagnostics.question_id == "CONFIRM_READBACK"


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


def test_inbound_transfer_without_a_booking_still_needs_no_clinic_write() -> None:
    bot, clinic, _ = _bot("c_inbound_transfer", direction="inbound")
    action = _run(bot, "c_inbound_transfer", ["cho tôi gặp nhân viên"])
    assert action.outcome == "TRANSFERRED" and clinic.requests == []
