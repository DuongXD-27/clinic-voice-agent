class SevereFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def check_identity_verified_before_disclosure(identity_verified: bool) -> None:
    if not identity_verified:
        raise SevereFailure(
            "SF-03", "Không được tiết lộ chi tiết lịch hẹn trước khi xác minh danh tính"
        )


def check_slot_from_this_call(slot_id: str, slots_returned_this_call: set[str]) -> None:
    if slot_id not in slots_returned_this_call:
        raise SevereFailure(
            "SF-02", f"Slot {slot_id} không nằm trong danh sách GET /slots của cuộc gọi này"
        )


def check_writing_correct_appointment(
    target_appointment_id: str, call_appointment_id: str
) -> None:
    if target_appointment_id != call_appointment_id:
        raise SevereFailure(
            "SF-01", "Đang ghi nhầm vào appointment khác với appointment của cuộc gọi"
        )


def check_second_confirmation(confirmed_twice: bool) -> None:
    if not confirmed_twice:
        raise SevereFailure("SF-05", "Hủy lịch cần xác nhận ý định lần thứ hai")
