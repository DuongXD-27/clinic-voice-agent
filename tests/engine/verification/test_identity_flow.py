"""Luồng PDF qua orchestrator thật: tra cứu ở lượt 0, đối chiếu không gọi Mock.

Các case plan T-01 §6 bước 7 định thêm vào `identity_cases.py` (TC_ID_14–17) đặt ở đây để không sửa
test của A. Nhánh "không có ứng viên -> không hỏi tên, lượt 1 chuyển máy" thuộc T-02 (opening của A):
Inbound lỗi tra cứu chuyển máy ở lượt 1; outbound lỗi tra cứu không mở phiên.
"""

import pytest

from callbot.engine import CallerInput, CallStart, create_orchestrator
from callbot.engine.errors import OutboundStartFailed
from callbot.engine.session import CallContext
from clinic_mock_sim import FakeClinicAPI

NAME, DOB = "Nguyễn Văn A", "14/03/1978"


def _inbound(call_id: str, phone: str) -> CallStart:
    return CallStart(call_id=call_id, direction="inbound", caller_number=phone)


def _outbound(call_id: str) -> CallStart:
    return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")


def _ctx(bot, call_id: str) -> CallContext:
    return CallContext.from_dict(bot.sessions.store.get_session(call_id).context)


def _identity_turns(bot, call_id: str, name: str = NAME, dob: str = DOB):
    bot.handle_turn(call_id, CallerInput(turn=1, text=name))
    return bot.handle_turn(call_id, CallerInput(turn=2, text=dob))


def test_lookup_happens_at_turn_zero_and_verify_adds_no_request() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_t0", "0912345600"))
    assert clinic.patient_lookups == ["0912345600"]
    ctx = _ctx(bot, "c_t0")
    assert ctx.identity_lookup == "LOADED" and len(ctx.identity_reference) == 1
    calls_after_opening = len(clinic.calls)

    action = _identity_turns(bot, "c_t0")

    assert action.state == "AWAITING_INTENT"
    assert len(clinic.calls) == calls_after_opening  # verify không gọi mock
    assert clinic.patient_lookups == ["0912345600"]
    assert _ctx(bot, "c_t0").patient_id == "pt_3391"
    assert clinic.writes == []


def test_outbound_reads_appointment_at_turn_zero_and_holds_reference() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)

    bot.start_call(_outbound("c_out0"))

    assert [(c.method, c.path) for c in clinic.calls] == [("GET", "/appointments/apt_00417")]
    ctx = _ctx(bot, "c_out0")
    assert ctx.identity_lookup == "LOADED"
    assert ctx.identity_reference == [
        {
            "patient_id": "pt_3391",
            "full_name": "Nguyễn Văn A",
            "dob": "1978-03-14",
            "verifiable": True,
        }
    ]


def test_e164_caller_number_is_normalized_before_lookup() -> None:  # TC_ID_16
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_e164", "+84912345600"))
    action = _identity_turns(bot, "c_e164")

    assert clinic.patient_lookups == ["0912345600"]
    assert action.state == "AWAITING_INTENT"


def test_inbound_known_phone_wrong_name_is_patient_not_found_without_write() -> None:  # TC_ID_14
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_wrong", "0912345600"))
    action = _identity_turns(bot, "c_wrong", name="Trần Văn B")

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_NOT_FOUND")
    assert clinic.writes == [] and clinic.requests == []


def test_inbound_two_candidates_same_phone_verifies_the_matching_one() -> None:  # TC_ID_15
    clinic = FakeClinicAPI()
    clinic.seed_patient(
        {
            "patient_id": "pt_other",
            "phone": "0912345600",
            "verify": {"full_name": "Trần Văn B", "dob": "1980-01-01"},
        }
    )
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_two", "0912345600"))
    assert len(_ctx(bot, "c_two").identity_reference) == 2
    action = _identity_turns(bot, "c_two")

    assert action.state == "AWAITING_INTENT"
    assert _ctx(bot, "c_two").patient_id == "pt_3391"


def test_inbound_two_full_matches_transfers_instead_of_guessing() -> None:
    clinic = FakeClinicAPI()
    clinic.seed_patient(
        {
            "patient_id": "pt_twin",
            "phone": "0912345600",
            "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
        }
    )
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_twin", "0912345600"))
    action = _identity_turns(bot, "c_twin")

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_NOT_FOUND")
    assert bot.sessions.store.get_session("c_twin").context == {}
    assert clinic.writes == []


def test_outbound_verify_null_fails_identity_and_writes_transfer() -> None:  # TC_ID_17
    clinic = FakeClinicAPI()
    clinic.appointments["apt_00417"]["patient"]["verify"] = None
    bot = create_orchestrator(clinic)

    bot.start_call(_outbound("c_null"))
    action = _identity_turns(bot, "c_null")

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "IDENTITY_FAILED")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "IDENTITY_FAILED"})]


def test_outbound_mock_down_does_not_create_session_and_can_retry_after_recovery() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("get_appointment")
    bot = create_orchestrator(clinic)

    with pytest.raises(OutboundStartFailed):
        bot.start_call(_outbound("c_down"))
    assert bot.sessions.store.get_session("c_down") is None
    assert clinic.writes == []

    opening = bot.start_call(_outbound("c_down"))
    assert opening.state == "AWAITING_IDENTITY"
    assert _ctx(bot, "c_down").identity_lookup == "LOADED"
    assert _ctx(bot, "c_down").question is not None
    assert clinic.writes == []


def test_unregistered_inbound_caller_never_triggers_a_write() -> None:  # TC_ID_13 cốt lõi
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)

    bot.start_call(_inbound("c_unreg", "0999999999"))
    ctx = _ctx(bot, "c_unreg")
    assert (ctx.identity_lookup, ctx.identity_reference) == ("NO_CANDIDATES", [])
    assert ctx.question is None  # T-02: không hỏi tên
    action = bot.handle_turn("c_unreg", CallerInput(turn=1, text=NAME))

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_NOT_FOUND")
    assert clinic.patient_lookups == ["0999999999"]
    assert clinic.writes == [] and clinic.requests == []
