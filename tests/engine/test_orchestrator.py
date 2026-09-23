"""Orchestrator thật + Information Extraction mới trên clinic giả (F-04)."""

from dataclasses import fields
from datetime import date
from typing import Optional

import pytest

from callbot.engine import CallEnded, CallerInput, CallStart, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.templates import AI_DISCLOSURE
from callbot.engine.extraction import InformationExtractor, QuestionId, TurnContext
from callbot.engine.session import CallContext
from callbot.engine.verification import matches
from callbot.engine.verification.names import normalize_name
from callbot.tracing import Tracer
from callbot.tracing.pseudonym import CallKeyFactory
from tests.engine.fake_clinic import FakeClinicAPI, clinic_error

SILENCE = None


def _run(orchestrator, call_id: str, lines: list[Optional[str]], start: int = 1):
    action = None
    for turn, line in enumerate(lines, start=start):
        caller = (
            CallerInput(turn=turn, text=None, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        action = orchestrator.handle_turn(call_id, caller)
    return action


def _outbound(call_id: str) -> CallStart:
    return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")


def _inbound(call_id: str, phone: str = "0912345600") -> CallStart:
    return CallStart(call_id=call_id, direction="inbound", caller_number=phone)


def _context(bot, call_id: str) -> CallContext:
    return CallContext.from_dict(bot.sessions.store.get_session(call_id).context)


def test_name_normalizer_moved_to_verification() -> None:
    assert normalize_name("Nguyễn  Văn A") == "nguyen van a"


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
        # Số dạng +84 (Hình 0 contract) chuẩn hóa về số có hồ sơ trong fake
        bot.start_call(
            CallStart(call_id="c_greet_in", direction="inbound", caller_number="+84912345600")
        ),
    ]
    for opening in openings:
        assert AI_DISCLOSURE in opening.utterance
        assert opening.state == "AWAITING_IDENTITY"
        # [R-02] hỏi tên bằng câu hỏi mở, không đọc tên sẵn cho người nghe xác nhận
        assert opening.utterance.rstrip().endswith("?")
    assert _context(bot, "c_greet_out").question.question_id is QuestionId.ASK_NAME

    # T-02: không có hồ sơ -> không hỏi tên, nhưng vẫn công bố AI ngay câu đầu
    handoff = bot.start_call(_inbound("c_greet_unknown", "0999999999"))
    assert AI_DISCLOSURE in handoff.utterance and handoff.state == "AWAITING_IDENTITY"
    assert _context(bot, "c_greet_unknown").question is None


def test_confirm_attendance_in_one_readback_turn(monkeypatch) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_confirm"))
    summary = _run(bot, "c_confirm", ["Nguyễn Văn A", "14/03/1978"])
    assert summary.state == "AWAITING_INTENT" and "14 tháng 10" in summary.utterance
    assert _context(bot, "c_confirm").question.question_id is QuestionId.CONFIRM_READBACK

    evidence = []
    confirm = bot._dialogue._gateway.confirm

    def capture(ctx):
        evidence.extend(ctx.evidence)
        return confirm(ctx)

    monkeypatch.setattr(bot._dialogue._gateway, "confirm", capture)
    action = _run(bot, "c_confirm", ["Có, tôi đến được."], start=3)
    assert action.outcome == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
    assert bot.sessions.store.get_session("c_confirm").context == {}
    assert [(e.kind, e.label, e.question_id, e.turn) for e in evidence] == [
        ("CONFIRMATION", "AGREE", QuestionId.CONFIRM_READBACK, 3)
    ]


def test_rejected_confirm_write_does_not_report_confirmed() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_confirm_rejected"))
    _run(bot, "c_confirm_rejected", ["Nguyễn Văn A", "14/03/1978"])

    action = _run(bot, "c_confirm_rejected", ["Có, tôi đến được."], start=3)
    session = bot.sessions.store.get_session("c_confirm_rejected")
    appointment = clinic.appointments["apt_00417"]

    assert not any(operation == "CONFIRMED" for _, operation, _ in clinic.writes)
    assert appointment.get("confirmed_at") is None
    assert appointment.get("confirmed_via") is None
    assert (action.state, action.outcome, action.transfer_reason) == (
        "ENDED",
        "TRANSFERRED",
        "SYSTEM_ERROR",
    )
    assert session is not None and session.ended
    assert session.context == {}
    assert appointment["status"] == "TRANSFERRED"
    assert appointment["version"] == 4
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]


def test_ambiguous_attendance_answer_does_not_confirm() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_confirm_ambiguous"))
    summary = _run(bot, "c_confirm_ambiguous", ["Nguyễn Văn A", "14/03/1978"])
    assert _context(bot, "c_confirm_ambiguous").question.question_id is QuestionId.CONFIRM_READBACK
    assert "14 tháng 10" in summary.utterance

    action = _run(bot, "c_confirm_ambiguous", ["Để xem đã."], start=3)

    assert clinic.appointments["apt_00417"]["status"] != "CONFIRMED"
    assert clinic.requests == []
    assert clinic.writes == []
    assert action.outcome != "CONFIRMED"


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


def test_reschedule_slot_taken_reoffers_and_needs_new_confirmation() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_taken"))
    _run(bot, "c_taken", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đổi lịch", "hai giờ rưỡi chiều"])

    clinic.taken_slots.add("slot_91d2")  # người khác vừa lấy
    action = _run(bot, "c_taken", ["Được"], start=5)
    assert action.state == "OFFERING_SLOTS" and action.utterance.startswith(t.SLOT_TAKEN)
    assert "2 giờ 30 chiều" not in action.utterance
    ctx = _context(bot, "c_taken")
    assert ctx.selected_slot_id is None and ctx.evidence == []
    assert clinic.writes == []

    action = _run(bot, "c_taken", ["khung 1", "được"], start=6)
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_aa01"})]


def test_ambiguous_slot_choice_does_not_pick_first_slot() -> None:
    clinic = FakeClinicAPI()
    clinic.slots.append({"slot_id": "slot_cc03", "starts_at": "2026-10-14T16:00:00+07:00"})
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_ambiguous"))
    _run(bot, "c_ambiguous", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đổi lịch"])

    action = _run(bot, "c_ambiguous", ["buổi chiều"], start=4)
    assert action.state == "OFFERING_SLOTS"
    ctx = _context(bot, "c_ambiguous")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_cc03"]
    assert ctx.selected_slot_id is None and ctx.failed_understandings == 0


def test_refusing_slots_drops_pending_action_without_writing() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_refuse_slot"))
    _run(bot, "c_refuse_slot", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đổi lịch"])

    action = _run(bot, "c_refuse_slot", ["thôi không đổi nữa"], start=4)
    assert action.state == "AWAITING_INTENT"
    ctx = _context(bot, "c_refuse_slot")
    assert ctx.pending_action is None and ctx.selected_slot_id is None
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK
    assert clinic.writes == []


def test_cancel_requires_explicit_second_confirmation(monkeypatch) -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_cancel"))
    action = _run(bot, "c_cancel", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch vì bận"])
    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []

    # SF-05: "Vâng" không hủy lịch — hỏi lại bằng câu lựa chọn
    action = _run(bot, "c_cancel", ["Vâng"], start=4)
    assert action.utterance == t.CANCEL_CHOICE and clinic.writes == []

    kinds = []
    cancel = bot._dialogue._gateway.cancel

    def capture(ctx, reason):
        kinds.extend((e.kind, e.turn) for e in ctx.evidence)
        return cancel(ctx, reason)

    monkeypatch.setattr(bot._dialogue._gateway, "cancel", capture)
    action = _run(bot, "c_cancel", ["Hủy giúp tôi"], start=5)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]
    assert bot.sessions.store.get_session("c_cancel").context == {}
    assert kinds == [("REQUEST", 3), ("CONFIRMATION", 5)]


def test_cancel_refused_keeps_appointment() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_cancel_no"))
    _run(bot, "c_cancel_no", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch"])
    action = _run(bot, "c_cancel_no", ["Thôi không hủy nữa"], start=4)
    assert action.state == "AWAITING_INTENT"
    assert _context(bot, "c_cancel_no").evidence == []
    assert clinic.writes == []


def test_unclear_confirmation_counts_from_second_time() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_unclear"))
    _run(bot, "c_unclear", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch"])

    _run(bot, "c_unclear", ["Vâng"], start=4)
    ctx = _context(bot, "c_unclear")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)
    _run(bot, "c_unclear", ["Dạ"], start=5)
    ctx = _context(bot, "c_unclear")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (2, 1)
    action = _run(bot, "c_unclear", ["Ừ"], start=6)
    assert action.transfer_reason == "NOT_UNDERSTOOD"
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


def test_repeat_request_rereads_pending_question_without_counting() -> None:
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_outbound("c_repeat"))
    _run(bot, "c_repeat", ["Nguyễn Văn A"])
    action = _run(bot, "c_repeat", ["gì cơ"], start=2)
    assert action.utterance == t.ASK_DOB
    assert _context(bot, "c_repeat").failed_understandings == 0


def test_inbound_booking_with_open_intent_question() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_book"))
    action = _run(bot, "c_book", ["Nguyễn Văn A", "14/03/1978"])
    assert action.utterance == t.ASK_INTENT_INBOUND

    # Câu hỏi mở: "vâng" không được suy ra thành đặt lịch
    action = _run(bot, "c_book", ["Vâng"], start=3)
    assert action.state == "AWAITING_INTENT" and clinic.slot_reads == 0

    action = _run(bot, "c_book", ["Tôi muốn đặt lịch khám", "khung 2", "Đồng ý"], start=4)
    assert action.outcome == "BOOKED"
    assert clinic.writes == [("apt_new_1", "BOOKED", {"slot_id": "slot_91d2"})]


def test_clinical_question_transfers() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_clinical"))
    action = _run(
        bot, "c_clinical", ["Nguyễn Văn A", "14/03/1978", "Tôi bị đau ngực có sao không?"]
    )
    assert action.transfer_reason == "CLINICAL_QUESTION"


def test_request_human_transfers_before_verification() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_human"))
    action = _run(bot, "c_human", ["cho tôi gặp nhân viên"])
    assert action.transfer_reason == "PATIENT_REQUEST"
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "PATIENT_REQUEST"})]


def test_outbound_three_silent_turns_marks_unreachable() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_silent"))
    action = _run(bot, "c_silent", [SILENCE, SILENCE, SILENCE])
    assert action.outcome == "UNREACHABLE"
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": "SILENCE"})]
    assert clinic.appointments["apt_00417"]["attempt_count"] == 1


def test_rejected_unreachable_write_transfers_instead_of_reporting_success() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    clinic.fail_next("mark_unreachable", clinic_error(409, "VERSION_CONFLICT"))
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_unreachable_rejected"))

    action = _run(bot, "c_unreachable_rejected", [SILENCE, SILENCE, SILENCE])
    appointment = clinic.appointments["apt_00417"]

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert appointment["attempt_count"] == 0
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "SYSTEM_ERROR"})]


def test_inbound_silence_transfers_without_booking() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_inbound("c_in_silent"))
    action = _run(bot, "c_in_silent", [SILENCE, SILENCE, SILENCE])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == []


def test_voicemail_ends_unreachable_without_disclosing() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_voicemail"))
    action = _run(bot, "c_voicemail", ["Xin vui lòng để lại lời nhắn sau tiếng bíp"])
    assert action.outcome == "UNREACHABLE" and action.utterance == t.GOODBYE_UNREACHABLE
    assert "14 tháng 10" not in action.utterance
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": "VOICEMAIL"})]


def test_two_failed_understandings_transfer() -> None:
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_outbound("c_confused"))
    action = _run(bot, "c_confused", ["ờ để xem", "ờ để xem"])
    assert action.transfer_reason == "NOT_UNDERSTOOD"


def test_extraction_with_provenance_is_stored_on_turn_record() -> None:
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_outbound("c_trace"))
    _run(bot, "c_trace", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch"])
    record = bot.sessions.store.get_turn("c_trace", 3)
    assert record.extraction["question_id"] == "CONFIRM_READBACK"
    assert record.extraction["intent"] == {
        "value": "CANCEL",
        "provenance": "EXACT",
        "span": "hủy",
    }
    assert record.extraction["full_name"]["provenance"] == "NONE"


class _SpyExtractor(InformationExtractor):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[TurnContext] = []

    def extract(self, ctx, transcript, *, silence_ms=0):
        self.contexts.append(ctx)
        return super().extract(ctx, transcript, silence_ms=silence_ms)


def test_extractor_never_sees_patient_identity() -> None:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    spy = _SpyExtractor()
    bot._extractor = spy
    bot.start_call(_outbound("c_private"))
    # Người gọi nói sai tên: không được "sửa" theo hồ sơ
    _run(bot, "c_private", ["Nguyễn Văn Bê", "14/03/1978"])

    # Danh sách này là chốt chặn: thêm trường vào TurnContext phải cân nhắc nguyên tắc 2 rồi mới
    # sửa test. `pending_action` và `question_turn` là trạng thái hội thoại (T-05 §8.3.2),
    # không phải hồ sơ bệnh nhân hay chi tiết lịch hẹn.
    assert {f.name for f in fields(TurnContext)} == {
        "turn",
        "question_id",
        "direction",
        "now",
        "slots",
        "presented_slot_ids",
        "pending_action",
        "question_turn",
    }
    verify = clinic.appointments["apt_00417"]["patient"]["verify"]
    for seen in spy.contexts:
        dumped = repr(seen)
        assert verify["full_name"] not in dumped and verify["dob"] not in dumped
        assert "pt_3391" not in dumped
    session = bot.sessions.store.get_session("c_private")
    assert session.context == {} and session.ended


def test_trace_failure_does_not_rerun_committed_turn() -> None:
    class BrokenSink:
        calls = 0

        def emit(self, span) -> None:
            del span
            self.calls += 1
            raise OSError("disk full")

    sink = BrokenSink()
    tracer = Tracer(
        sink,
        CallKeyFactory("trace-test-secret-key-material-00000", version="v1", environment="test"),
    )
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, tracer=tracer)
    with tracer.start_trace(
        call_id="c_trace_fail", turn=0, component="TURN", operation="http.start_call"
    ):
        bot.start_call(_outbound("c_trace_fail"))
    first = None
    for turn, text in enumerate(["Nguyễn Văn A", "14/03/1978", "Có, tôi đến được"], start=1):
        with tracer.start_trace(
            call_id="c_trace_fail", turn=turn, component="TURN", operation="http.call_turn"
        ):
            first = bot.handle_turn("c_trace_fail", CallerInput(turn=turn, text=text))
    assert first is not None
    assert first.outcome == "CONFIRMED"
    assert sink.calls > 0
    with pytest.raises(CallEnded):
        bot.handle_turn("c_trace_fail", CallerInput(turn=3, text="Có, tôi đến được"))
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
