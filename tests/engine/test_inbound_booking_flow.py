import pytest
from typing import Any

from callbot.engine.types import BotAction
from callbot.engine.errors import ReconciliationRequired
from tests.engine.fake_clinic import FakeClinicAPI
from tests.engine.test_orchestrator import create_orchestrator, _run, SILENCE, _inbound, t

class CustomFakeClinic(FakeClinicAPI):
    def __init__(self, override_status: str | None = "BOOKED", override_id: str | None = "apt_new_1"):
        super().__init__()
        self.override_status = override_status
        self.override_id = override_id

    def create_appointment(self, patient_id: str, slot_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
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
    
    action = _run(bot, "c_book_1", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"])
    
    assert action.outcome == "BOOKED"
    assert action.ended is True


def test_inbound_booking_wrong_status_aborts_turn() -> None:
    # Test 8
    clinic = CustomFakeClinic(override_status="SCHEDULED")
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_2"))
    
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_book_2", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"])
    
    session = bot.sessions.store.get_session("c_book_2")
    assert session.context.get("created_appointment_id") is None


def test_inbound_booking_missing_status_aborts_turn() -> None:
    # Test 9
    clinic = CustomFakeClinic(override_status=None)
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_3"))
    
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_book_3", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"])
    
    session = bot.sessions.store.get_session("c_book_3")
    assert session.context.get("created_appointment_id") is None


def test_inbound_booking_missing_id_aborts_turn() -> None:
    # Test 10
    clinic = CustomFakeClinic(override_id=None)
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book_4"))
    
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_book_4", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "Khung 2", "Đúng rồi đặt cho tôi"])
    
    session = bot.sessions.store.get_session("c_book_4")
    assert session.context.get("created_appointment_id") is None
