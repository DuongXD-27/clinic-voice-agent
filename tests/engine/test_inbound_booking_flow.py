from typing import Any

import pytest

from callbot.engine.dialogue import templates as t
from callbot.engine.errors import ReconciliationRequired
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_orchestrator import SILENCE, _context, _inbound, _run, create_orchestrator


class CustomFakeClinic(FakeClinicAPI):
    def __init__(
        self, override_status: str | None = "BOOKED", override_id: str | None = "apt_new_1"
    ):
        super().__init__()
        self.override_status = override_status
        self.override_id = override_id

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        # Bỏ qua logic create thật, trả về kết quả giả
        rec = {}
        if self.override_id is not None:
            rec["appointment_id"] = self.override_id
        if self.override_status is not None:
            rec["status"] = self.override_status
        return rec


def test_inbound_booking_happy_path() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_1"))

    action = _run(
        bot,
        "c_book_1",
        ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"],
    )

    assert action.outcome == "BOOKED"
    assert action.ended is True


def test_inbound_booking_wrong_status_aborts_turn() -> None:
    # Test 8
    clinic = CustomFakeClinic(override_status="SCHEDULED")
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_2"))

    with pytest.raises(ReconciliationRequired):
        _run(
            bot,
            "c_book_2",
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"],
        )

    session = bot.sessions.store.get_session("c_book_2")
    assert session.context.get("created_appointment_id") is None


def test_inbound_booking_missing_status_aborts_turn() -> None:
    # Test 9
    clinic = CustomFakeClinic(override_status=None)
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_3"))

    with pytest.raises(ReconciliationRequired):
        _run(
            bot,
            "c_book_3",
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"],
        )

    session = bot.sessions.store.get_session("c_book_3")
    assert session.context.get("created_appointment_id") is None


def test_inbound_booking_missing_id_aborts_turn() -> None:
    # Test 10
    clinic = CustomFakeClinic(override_id=None)
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_4"))

    with pytest.raises(ReconciliationRequired):
        _run(
            bot,
            "c_book_4",
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"],
        )

    session = bot.sessions.store.get_session("c_book_4")
    assert session.context.get("created_appointment_id") is None


# --- Inbound không có caller_number: tên, ngày sinh rồi số điện thoại đã đăng ký (§1.1.9) ------

NAME, DOB = "Nguyễn Văn A", "14/03/1978"
BOOKING = ["Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"]
# Chi tiết hồ sơ / lịch không được lộ trước khi xác minh xong (SF-03)
_PROTECTED = ("nguyễn văn a", "1978", "14 tháng 3", "0912345600", "nội tổng quát")


def _assert_nothing_disclosed(actions) -> None:
    for action in actions:
        said = action.utterance.lower()
        assert not any(value in said for value in _PROTECTED), action.utterance


def _start_without_number(call_id: str, clinic: FakeClinicAPI | None = None):
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    opening = bot.start_call(_inbound(call_id, None))
    assert opening.utterance == t.GREETING_INBOUND and opening.state == "AWAITING_IDENTITY"
    assert _context(bot, call_id).identity_lookup == "AWAITING_PHONE"
    return bot, clinic, opening


@pytest.mark.parametrize(
    "spoken_phone",
    [
        "0912345600",
        "84912345600",  # đầu số "84" trần, không có dấu +
        "84 0912 345 600",
        "+84 912 345 600",
        "Dạ số tôi là không chín một hai ba bốn năm sáu không không ạ",
        "tám bốn chín một hai ba bốn năm sáu không không",
        "0912 345 601, à không, 0912 345 600",  # R-44: số nói sau cùng
    ],
)
def test_inbound_without_caller_number_asks_phone_after_dob_then_books(spoken_phone: str) -> None:
    bot, clinic, opening = _start_without_number("c_book_nophone")

    asked_phone = _run(bot, "c_book_nophone", [NAME, DOB])
    assert asked_phone.utterance in t.static_choices(t.ASK_PHONE)
    assert asked_phone.state == "AWAITING_IDENTITY" and not asked_phone.ended
    assert clinic.calls == []  # chưa có số thì chưa tra cứu
    assert _context(bot, "c_book_nophone").identity_step == "ASK_PHONE"

    verified = _run(bot, "c_book_nophone", [spoken_phone], start=3)
    assert verified.utterance in t.static_choices(t.ASK_INTENT_INBOUND)
    assert verified.state == "AWAITING_INTENT"
    assert clinic.patient_lookups == ["0912345600"] and clinic.writes == []
    ctx = _context(bot, "c_book_nophone")
    assert ctx.identity_lookup == "LOADED" and ctx.identity_verified
    _assert_nothing_disclosed([opening, asked_phone, verified])

    action = _run(bot, "c_book_nophone", BOOKING, start=4)
    assert (action.outcome, action.ended) == ("BOOKED", True)
    assert [status for _, status, _ in clinic.writes] == ["BOOKED"]


def test_inbound_without_caller_number_verifies_only_after_the_phone_lookup() -> None:
    """Số chỉ để tìm hồ sơ (§1.1.9): ngày sinh sai vẫn hỏi số như thường, có hồ sơ mới đối chiếu và
    chuyển máy — không nói yếu tố nào sai (§1.1.2)."""
    bot, clinic, _ = _start_without_number("c_nophone_wrong_dob")
    asked_phone = _run(bot, "c_nophone_wrong_dob", [NAME, "15/03/1978"])
    assert asked_phone.utterance in t.static_choices(t.ASK_PHONE)

    action = _run(bot, "c_nophone_wrong_dob", ["0912345600"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_NOT_FOUND")
    assert action.utterance == t.IDENTITY_FAILED_TRANSFER
    assert clinic.patient_lookups == ["0912345600"] and clinic.writes == []


def test_inbound_without_caller_number_unknown_phone_is_patient_not_found() -> None:
    bot, clinic, _ = _start_without_number("c_nophone_unknown")
    action = _run(bot, "c_nophone_unknown", [NAME, DOB, "0999999999"])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_NOT_FOUND")
    assert action.utterance == t.IDENTITY_FAILED_TRANSFER
    assert clinic.patient_lookups == ["0999999999"] and clinic.writes == []


def test_inbound_without_caller_number_lookup_failure_is_system_error() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("find_patient_by_phone")
    bot, _, _ = _start_without_number("c_nophone_down", clinic)
    action = _run(bot, "c_nophone_down", [NAME, DOB, "0912345600"])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert clinic.writes == []


@pytest.mark.parametrize(
    "answers",
    [
        ["tôi không nhớ số", "để tôi tìm đã"],
        ["091234560", "0112345678"],  # 9 chữ số, rồi đầu số ngoài dạng mock nhận
    ],
)
def test_inbound_without_caller_number_asks_phone_once_more_then_transfers(
    answers: list[str],
) -> None:
    bot, clinic, _ = _start_without_number("c_nophone_retry")
    retry = _run(bot, "c_nophone_retry", [NAME, DOB, answers[0]])
    assert retry.utterance in t.static_choices(t.ASK_PHONE_AGAIN) and not retry.ended

    action = _run(bot, "c_nophone_retry", [answers[1]], start=4)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.calls == [] and clinic.writes == []


def test_inbound_without_caller_number_recovers_after_one_unclear_answer() -> None:
    bot, clinic, _ = _start_without_number("c_nophone_recover")
    retry = _run(bot, "c_nophone_recover", [NAME, DOB, "để tôi xem đã"])
    assert retry.utterance in t.static_choices(t.ASK_PHONE_AGAIN)
    verified = _run(bot, "c_nophone_recover", ["0912345600"], start=4)
    assert verified.state == "AWAITING_INTENT"
    assert clinic.patient_lookups == ["0912345600"]


def test_booking_request_at_the_phone_question_is_answered_with_the_reason() -> None:
    """Nêu nhu cầu thay vì đọc số: vẫn là lượt hỏi lại (R-40) nhưng nói rõ vì sao cần số."""
    bot, clinic, _ = _start_without_number("c_nophone_book")
    asked = _run(bot, "c_nophone_book", [NAME, DOB, "Tôi muốn đặt lịch khám"])
    assert asked.utterance in t.static_choices(t.ASK_PHONE_FOR_REQUEST) and not asked.ended
    assert clinic.calls == []
    verified = _run(bot, "c_nophone_book", ["0912345600"], start=4)
    assert verified.state == "AWAITING_INTENT"
    action = _run(bot, "c_nophone_book", BOOKING, start=5)
    assert (action.outcome, action.ended) == ("BOOKED", True)


@pytest.mark.parametrize("filler", ["Alo, ai đấy?", SILENCE, "chờ tôi một chút"])
def test_identity_question_silence_or_hold_at_the_phone_question_does_not_spend_the_retry(
    filler,
) -> None:
    bot, clinic, _ = _start_without_number("c_nophone_social")
    reply = _run(bot, "c_nophone_social", [NAME, DOB, filler])
    assert reply.state == "AWAITING_IDENTITY" and not reply.ended
    # Giữ máy: chỉ đáp lời, câu hỏi số vẫn đang chờ; "ai đấy?" / im lặng: nhắc lại câu hỏi số
    assert reply.utterance == t.HOLD or "số điện thoại" in reply.utterance
    retry = _run(bot, "c_nophone_social", ["để tôi xem đã"], start=4)
    assert retry.utterance in t.static_choices(t.ASK_PHONE_AGAIN) and not retry.ended
    verified = _run(bot, "c_nophone_social", ["0912345600"], start=5)
    assert verified.state == "AWAITING_INTENT"
    assert clinic.patient_lookups == ["0912345600"]


@pytest.mark.parametrize(
    "line, reason",
    [
        ("Cho hỏi đặt lịch có dùng bảo hiểm y tế được không?", "OUT_OF_SCOPE"),
        ("cho tôi gặp nhân viên", "PATIENT_REQUEST"),
        ("tôi đau ngực quá", "CLINICAL_QUESTION"),
    ],
)
def test_policy_signals_at_the_phone_question_still_transfer(line: str, reason: str) -> None:
    bot, clinic, _ = _start_without_number("c_nophone_policy")
    action = _run(bot, "c_nophone_policy", [NAME, DOB, line])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)
    assert clinic.calls == [] and clinic.writes == []


def test_inbound_with_caller_number_does_not_ask_for_the_phone() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_withphone"))
    verified = _run(bot, "c_book_withphone", [NAME, DOB])
    assert verified.state == "AWAITING_INTENT"
    assert clinic.patient_lookups == ["0912345600"]
