"""Máy trạng thái lịch hẹn — tương ứng `clinic-mock/src/clinic_mock/lifecycle.py`.

Bảng giữ y như mock. Riêng unreachable, route của mock cho phép thêm UNREACHABLE → UNREACHABLE
(mỗi lần gọi tăng attempt_count) — xem `assert_unreachable_transition`.
"""

from clinic_mock_sim.errors import conflict

APPOINTMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "confirm": frozenset({"SCHEDULED", "BOOKED", "CONFIRMED"}),
    "cancel": frozenset({"SCHEDULED", "BOOKED", "CONFIRMED"}),
    "transfer": frozenset({"SCHEDULED", "BOOKED", "CONFIRMED"}),
    "reschedule": frozenset({"SCHEDULED", "BOOKED", "CONFIRMED"}),
    "unreachable": frozenset({"SCHEDULED", "BOOKED"}),
}


def assert_appointment_transition(current: str, action: str) -> None:
    if current not in APPOINTMENT_TRANSITIONS[action]:
        raise conflict(
            "INVALID_STATE_TRANSITION", f"Cannot {action} an appointment in status {current}."
        )


def assert_unreachable_transition(current: str) -> None:
    # routes.py mark_unreachable: `if appt.status not in {SCHEDULED, BOOKED, UNREACHABLE}: assert...`
    if current != "UNREACHABLE":
        assert_appointment_transition(current, "unreachable")
