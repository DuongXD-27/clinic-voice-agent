from datetime import date

from callbot.engine import CallerInput, CallStart, create_orchestrator
from callbot.engine.dialogue.templates import AI_DISCLOSURE
from callbot.engine.nlu.normalizer import normalize_name, parse_dob
from callbot.engine.verification import matches
from tests.engine.fake_clinic import FakeClinicAPI


def _run(orchestrator, call_id: str, lines: list[str | None]):
    action = None
    for turn, line in enumerate(lines, start=1):
        caller = (
            CallerInput(turn=turn, is_silence=True)
            if line is None
            else CallerInput(turn=turn, text=line)
        )
        action = orchestrator.handle_turn(call_id, caller)
    return action


def _outbound(call_id: str) -> CallStart:
    return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")


def test_normalizer() -> None:
    assert normalize_name("Nguyễn  Văn A") == "nguyen van a"
    assert parse_dob("Ngày 14 tháng 3 năm 1978.") == date(1978, 3, 14)
    assert parse_dob("14/03/1978") == date(1978, 3, 14)
    assert parse_dob("không nhớ") is None


def test_identity_match() -> None:
    verify = {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"}
    assert matches("nguyễn văn a", date(1978, 3, 14), verify)
    assert not matches("nguyễn văn b", date(1978, 3, 14), verify)
    assert not matches("nguyễn văn a", date(1978, 3, 15), verify)


def test_opening_discloses_ai_assistant() -> None:
    """[R-26]: câu chào đầu tiên công bố là trợ lý ảo AI, cả inbound lẫn outbound."""
    bot = create_orchestrator(FakeClinicAPI())
    openings = [
        bot.start_call(_outbound("c_greet_out")),
        bot.start_call(
            CallStart(call_id="c_greet_in", direction="inbound", caller_number="+84987654321")
        ),
    ]
    for opening in openings:
        assert AI_DISCLOSURE in opening.utterance
        assert opening.state == "AWAITING_IDENTITY"
        # [R-02] hỏi tên bằng câu hỏi mở, không đọc tên sẵn cho người nghe xác nhận
        assert opening.utterance.rstrip().endswith("?")


def test_reference_call_reschedule() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    opening = bot.start_call(_outbound("c_resched"))
    assert "14 tháng 10" not in opening.utterance

    action = _run(
        bot,
        "c_resched",
        [
            "Nguyễn Văn A.",
            "Ngày 14 tháng 3 năm 1978.",
            "Tôi đổi sang buổi chiều được không?",
            "khung 1",
            "Được, đổi giúp tôi.",
        ],
    )
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


def test_identity_mismatch_transfers_without_disclosure() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_wrong_id"))
    action = _run(bot, "c_wrong_id", ["Trần Thị B", "Ngày 1 tháng 1 năm 1990"])
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "IDENTITY_FAILED"
    assert "Nội tổng quát" not in action.utterance


def test_cancel_requires_second_confirmation() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_cancel"))
    action = _run(bot, "c_cancel", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch"])
    assert action.ended is False and clinic.writes == []

    action = bot.handle_turn("c_cancel", CallerInput(turn=4, text="Vâng"))
    assert action.outcome == "CANCELLED"


def test_clinical_question_transfers() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_clinical"))
    action = _run(
        bot, "c_clinical", ["Nguyễn Văn A", "14/03/1978", "Tôi bị đau ngực có sao không?"]
    )
    assert action.transfer_reason == "CLINICAL_QUESTION"


def test_three_silent_turns_unreachable() -> None:
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_outbound("c_silent"))
    action = _run(bot, "c_silent", [None, None, None])
    assert action.outcome == "UNREACHABLE"


def test_two_failed_understandings_transfer() -> None:
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_outbound("c_confused"))
    action = _run(bot, "c_confused", ["alo", "alo"])
    assert action.transfer_reason == "NOT_UNDERSTOOD"
