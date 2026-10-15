"""T-04 — hội thoại Confirm: chỉ trả CONFIRMED sau khi Clinic xác nhận ghi thành công (§1.1.3).

Orchestrator thật + FakeClinicAPI. apt_00417: 9 giờ sáng 14/10, cl_vinmec, Nội tổng quát.
"""

from typing import Any, Optional

import pytest

from callbot.engine import (
    CallEnded,
    CallerInput,
    CallStart,
    ReconciliationRequired,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction import QuestionId
from callbot.engine.extraction.schema import ClinicalLevel, Intent
from callbot.engine.extraction.semantic import ReplyKind, SemanticContext, SemanticOutcome
from callbot.engine.session import CallContext
from callbot.engine.tools.clinic_gateway import WRITE_MAX_SENDS
from clinic_mock_sim import FakeClinicAPI, clinic_error

SILENCE = None
FACTS = "9 giờ sáng, thứ Tư ngày 14 tháng 10, tại bệnh viện"
CONFIRMED_WRITE = ("apt_00417", "CONFIRMED", {})


def _run(bot, call_id: str, lines: list[Optional[str]], start: int = 1):
    action = None
    for turn, line in enumerate(lines, start=start):
        caller = (
            CallerInput(turn=turn, text=None, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        action = bot.handle_turn(call_id, caller)
    return action


def _context(bot, call_id: str) -> CallContext:
    return CallContext.from_dict(bot.sessions.store.get_session(call_id).context)


def _at_readback(call_id: str, clinic: Optional[FakeClinicAPI] = None):
    """Outbound đã xác minh, đang chờ câu tóm tắt gộp đọc lại (Figure 0). Lượt kế tiếp là 3."""
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    summary = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"])
    assert summary.state == "AWAITING_INTENT"
    return bot, clinic, summary


def _confirm_writes(clinic: FakeClinicAPI) -> list[tuple[str, str, dict[str, Any]]]:
    return [write for write in clinic.writes if write[1] == "CONFIRMED"]


# --- Đọc lại ngày, giờ, cơ sở (§1.1.3) ------------------------------------------------


def test_summary_reads_back_date_time_and_clinic_name() -> None:
    bot, clinic, summary = _at_readback("c_t04_summary")
    assert FACTS in summary.utterance and "Nội tổng quát" in summary.utterance
    assert _context(bot, "c_t04_summary").question.question_id is QuestionId.CONFIRM_READBACK
    assert clinic.writes == []


@pytest.mark.parametrize(
    "appointment,expected",
    [
        ({}, "bệnh viện"),
        ({"clinic_id": "cl_unknown"}, "bệnh viện"),
        ({"clinic_id": "cl_vinmec"}, "bệnh viện"),
        ({"clinic_name": "Vinmec Times City"}, "bệnh viện"),
        ({"clinic_name": "Vinmec Central Park"}, "bệnh viện"),
        ({"clinic_name": "Bệnh viện Đa khoa Quốc tế VINMEC Times City"}, "bệnh viện"),
        ({"clinic_id": "c_001"}, "Phòng khám Đa khoa Trung tâm"),
        ({"clinic_name": "Phòng khám Trung tâm"}, "Phòng khám Trung tâm"),
    ],
)
def test_clinic_name_uses_generic_hospital_for_brand_and_unknown_clinics(appointment, expected):
    original = dict(appointment)
    assert t.clinic_name(appointment) == expected
    assert appointment == original


# --- Đồng ý -> ghi, rồi mới báo CONFIRMED ------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Có, tôi đến được.",
        "vâng",
        "dạ",
        "ừ",
        "vâng, cảm ơn em",
        "tôi sẽ đến",  # Bảng 1: "states or agrees they will attend"
        "xác nhận",
        "giữ nguyên lịch",
        "không hủy đâu, tôi vẫn đến",
        "tôi biết địa chỉ rồi, tôi sẽ đến",
        "tôi sẽ đến đúng giờ, không trễ đâu",
        # Cụm trung tính ở câu hỏi đến khám không phải phủ định (R-41, ngoại lệ chờ PO duyệt)
        "không đổi gì đâu, tôi vẫn đến",
        # Nhận lịch / hoàn cảnh cho phép đến, kèm lời đồng ý (eval confirm 13-10)
        "lịch đó ổn em ạ",
        "ừ thế cũng được",
        "tôi thu xếp được rồi",
        "hôm đó tôi xin nghỉ rồi, đến được",
        "hôm đó tôi qua sớm",
    ],
)
def test_agreement_confirms_in_one_turn(answer: str) -> None:
    if answer in ("dạ",):
        bot, clinic, _ = _at_readback("c_unsafe")
        action = _run(bot, "c_unsafe", [answer], start=3)
        assert not action.ended and clinic.writes == []
        assert _context(bot, "c_unsafe").evidence == []
        return
    bot, clinic, _ = _at_readback("c_t04_agree")
    action = _run(bot, "c_t04_agree", [answer], start=3)
    assert (action.ended, action.outcome, action.state) == (True, "CONFIRMED", "ENDED")
    assert clinic.writes == [CONFIRMED_WRITE]
    # Câu báo dựng từ bản ghi Mock trả về sau lệnh ghi
    assert FACTS in action.utterance
    assert bot.sessions.store.get_session("c_t04_agree").context == {}


def test_success_message_uses_the_written_record() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_record", clinic)
    confirm = clinic.confirm_appointment

    def confirm_and_report_other_clinic(*args, **kwargs):
        return {**confirm(*args, **kwargs), "clinic_id": "c_002"}

    clinic.confirm_appointment = confirm_and_report_other_clinic
    action = _run(bot, "c_t04_record", ["vâng"], start=3)
    assert action.outcome == "CONFIRMED" and "Phòng khám Đa khoa Cầu Giấy" in action.utterance


# --- Chưa rõ: đọc lại bằng câu có / không, không ghi ---------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "ờ để xem",
        "chắc là được",
        "có lẽ vậy",
        "vâng để tôi xem lại",
        "được không em?",
        "mấy giờ nhỉ?",
        "tôi không biết địa chỉ, tôi sẽ đến",
        "tôi sẽ đến nếu không trễ",
        "tôi sẽ đến nhưng không đúng giờ",
    ],
)
def test_unclear_answer_rereads_without_writing(answer: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_unclear")
    action = _run(bot, "c_t04_unclear", [answer], start=3)
    assert not action.ended and clinic.writes == []
    assert FACTS in action.utterance and action.utterance.endswith(t.ASK_ATTENDANCE)
    ctx = _context(bot, "c_t04_unclear")
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK and ctx.question.turn == 3
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)
    assert ctx.evidence == []


def test_yes_after_reread_confirms_with_evidence_of_that_turn(monkeypatch) -> None:
    bot, clinic, _ = _at_readback("c_t04_reread")
    _run(bot, "c_t04_reread", ["chắc là được"], start=3)

    evidence = []
    confirm = bot._dialogue._gateway.confirm

    def capture(ctx):
        evidence.extend(ctx.evidence)
        return confirm(ctx)

    monkeypatch.setattr(bot._dialogue._gateway, "confirm", capture)
    action = _run(bot, "c_t04_reread", ["vâng"], start=4)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]
    assert [(e.kind, e.label, e.turn, e.question_turn) for e in evidence] == [
        ("CONFIRMATION", "AGREE", 4, 3)
    ]


def test_unclear_three_times_transfers_not_understood() -> None:
    bot, clinic, _ = _at_readback("c_t04_unclear3")
    action = _run(bot, "c_t04_unclear3", ["chắc là được", "có lẽ vậy", "để tôi xem đã"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


# --- Từ chối / đổi ý ------------------------------------------------------------------------


def test_refusal_drops_pending_and_changed_mind_needs_new_readback() -> None:
    bot, clinic, _ = _at_readback("c_t04_refuse")
    action = _run(bot, "c_t04_refuse", ["không"], start=3)
    assert action.utterance in t.static_choices(t.ASK_CHANGE_OR_CANCEL) and clinic.writes == []
    ctx = _context(bot, "c_t04_refuse")
    assert ctx.pending_action is None and ctx.evidence == []

    action = _run(bot, "c_t04_refuse", ["thôi tôi vẫn đến"], start=4)
    assert action.state == "AWAITING_CONFIRMATION" and FACTS in action.utterance
    assert clinic.writes == []

    action = _run(bot, "c_t04_refuse", ["đồng ý"], start=5)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


def test_yes_to_change_or_cancel_question_does_not_confirm() -> None:
    bot, clinic, _ = _at_readback("c_t04_open")
    action = _run(bot, "c_t04_open", ["không", "vâng"], start=3)
    assert not action.ended and clinic.writes == []


@pytest.mark.parametrize(
    "answer, state",
    [
        ("không đến được", "AWAITING_CONFIRMATION"),  # sang hủy, chờ xác nhận hủy lần hai
        ("vâng nhưng tôi muốn đổi giờ", "OFFERING_SLOTS"),
    ],
)
def test_cancel_or_reschedule_at_readback_does_not_confirm(answer: str, state: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_branch")
    action = _run(bot, "c_t04_branch", [answer], start=3)
    assert action.state == state and clinic.writes == []


# --- Ngoại lệ ở bước xác nhận ---------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, reason",
    [
        ("vâng, à mà tôi đau ngực", "CLINICAL_QUESTION"),
        ("thuốc huyết áp có phải ngưng trước khi khám không", "CLINICAL_QUESTION"),
        ("cho tôi gặp nhân viên", "PATIENT_REQUEST"),
    ],
)
def test_exceptions_at_readback_transfer_without_confirming(answer: str, reason: str) -> None:
    bot, clinic, _ = _at_readback("c_t04_exc")
    action = _run(bot, "c_t04_exc", [answer], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", reason)
    assert _confirm_writes(clinic) == []


@pytest.mark.parametrize(
    "answer",
    [
        "vợ tôi sẽ đến thay",
        "địa chỉ ở đâu em nhỉ",
        "tôi đến trễ không sao chứ",
        "dạ, tôi đang bận, gọi lại sau",
        "có mất phí không em",
        "khám lần này hết bao nhiêu tiền em",
        "kham lan nay het bao nhieu tien em",
        "lịch này tôi có đặt đâu em",
        "toi co dat lich nao dau",
        "ai đặt lịch này cho tôi vậy",
        "em nhắn tin lịch khám qua điện thoại cho tôi nhé",
        "tôi có hẹn gì bên mình đâu em",
    ],
)
def test_out_of_scope_answer_at_readback_transfers_instead_of_rereading(answer: str) -> None:
    """Câu bot hiểu nhưng ngoài kịch bản: chuyển máy ngay (§1.1.5), không đọc lại lịch để né."""
    bot, clinic, _ = _at_readback("c_t04_oos")
    action = _run(bot, "c_t04_oos", [answer], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "OUT_OF_SCOPE")
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_silence_and_repeat_request_keep_the_readback_question() -> None:
    bot, clinic, summary = _at_readback("c_t04_silence")
    action = _run(bot, "c_t04_silence", [SILENCE], start=3)
    # T-08: nhắc rồi đọc lại nguyên văn câu tóm tắt, hỏi lại ở lượt 3
    assert action.utterance == f"{t.SILENCE} {summary.utterance}"
    question = _context(bot, "c_t04_silence").question
    assert (question.text, question.turn) == (summary.utterance, 3)

    action = _run(bot, "c_t04_silence", ["gì cơ"], start=4)
    assert action.utterance == summary.utterance
    action = _run(bot, "c_t04_silence", ["vâng"], start=5)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


# --- Kết quả ghi: chỉ CONFIRMED khi Clinic xác nhận ----------------------------------------


def test_rejected_write_is_system_error_not_confirmed() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_rejected", clinic)
    clinic.fail_next("confirm_appointment", clinic_error(422, "IDEMPOTENCY_CONFLICT"))
    action = _run(bot, "c_t04_rejected", ["vâng"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert "xác nhận lịch khám" not in action.utterance
    assert _confirm_writes(clinic) == []
    assert [status for _, status, _ in clinic.writes] == ["TRANSFERRED"]


def test_invalid_state_transition_on_confirm_is_transferred() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_invalid_state", clinic)
    clinic.fail_next("confirm_appointment", clinic_error(409, "INVALID_STATE_TRANSITION"))
    action = _run(bot, "c_t04_invalid_state", ["vâng"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert "xác nhận lịch khám" not in action.utterance
    assert _confirm_writes(clinic) == []


def test_unknown_write_outcome_blocks_the_turn_instead_of_reporting() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_unknown", clinic)
    clinic.fail_unknown("confirm_appointment", WRITE_MAX_SENDS, apply_first=True)
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t04_unknown", ["vâng"], start=3)
    # Mock đã ghi nhưng bot không biết: không có phản hồi CONFIRMED, không chuyển máy thay thế
    assert clinic.writes == [CONFIRMED_WRITE]


def test_version_conflict_retries_with_same_key_then_confirms() -> None:
    """§4.2.5: đọc lại, gửi lại với version mới và cùng Idempotency-Key."""
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_conflict", clinic)
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    action = _run(bot, "c_t04_conflict", ["vâng"], start=3)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]
    keys = [key for key, label in clinic.requests if label == "CONFIRMED"]
    assert keys == ["c_t04_conflict:3:confirm"] * 2


def test_write_without_confirmed_status_is_not_reported_as_confirmed() -> None:
    clinic = FakeClinicAPI()
    bot, _, _ = _at_readback("c_t04_status", clinic)
    clinic.confirm_appointment = lambda *args, **kwargs: {
        **clinic.appointments["apt_00417"],
        "status": "SCHEDULED",
    }
    # Lệnh đã commit nên không ghi /transfer thay thế; lượt bị chặn để đối soát, không báo CONFIRMED
    with pytest.raises(ReconciliationRequired):
        _run(bot, "c_t04_status", ["vâng"], start=3)
    assert clinic.writes == []


def test_resent_confirm_turn_does_not_write_twice() -> None:
    """F-03: ghi Clinic xong thì nội dung phiên bị xóa — gửi lại lượt nhận CALL_ENDED, không ghi lần hai."""
    bot, clinic, _ = _at_readback("c_t04_replay")
    assert _run(bot, "c_t04_replay", ["vâng"], start=3).outcome == "CONFIRMED"
    with pytest.raises(CallEnded):
        _run(bot, "c_t04_replay", ["vâng"], start=3)
    assert clinic.writes == [CONFIRMED_WRITE]


# --- Inbound: xác nhận lịch có sẵn là ngoài kịch bản (§1, §1.1.5) -------------------------


def _inbound_at_intent(call_id: str):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id=call_id, direction="inbound", caller_number="0912345600"))
    action = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"])
    assert action.utterance == t.ASK_INTENT_INBOUND
    return bot, clinic


def test_inbound_confirm_request_transfers_at_once_without_write() -> None:
    bot, clinic = _inbound_at_intent("c_t04_in")
    action = _run(bot, "c_t04_in", ["tôi muốn xác nhận lịch khám"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "OUT_OF_SCOPE")
    assert clinic.writes == []


def test_inbound_attendance_wording_is_not_mistaken_for_confirm() -> None:
    bot, clinic = _inbound_at_intent("c_t04_in_book")
    action = _run(bot, "c_t04_in_book", ["sáng mai tôi đến được không"], start=3)
    assert not action.ended and clinic.writes == []


# --- T-04 §8: câu kể có từ khẳng định / đáp lễ không được mở khóa lệnh ghi ------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "dạ hôm đó tôi bận rồi",
        "hôm đó tôi có việc bận",
        "tôi phải đi làm hôm đó",
        "vâng, hôm đó tôi phải đi công tác",
        "hôm đó tôi sẽ đi công tác",
        "chắc được",
        "tôi sẽ đến lúc 10 giờ",
        "à",
    ],
)
def test_statements_with_a_yes_word_reread_without_writing(answer: str) -> None:
    bot, clinic, _ = _at_readback("c_t04s8_story")
    action = _run(bot, "c_t04s8_story", [answer], start=3)
    assert not action.ended and clinic.writes == []
    assert FACTS in action.utterance and action.utterance.endswith(t.ASK_ATTENDANCE)
    ctx = _context(bot, "c_t04s8_story")
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK and ctx.evidence == []


@pytest.mark.parametrize(
    "answer",
    [
        "lịch đó không ổn",
        "ổn không em",
        "lich do on em a",
        "ừ, vợ tôi cũng đi",
        "tôi chưa sắp xếp được",
        "để tôi sắp xếp đã",
        "hôm đó tôi nghỉ phép rồi, không đi được",
        "tôi không qua sớm được",
        "hom do toi qua som",
        "tôi qua sớm hơn",
        "không hủy, nhưng không đi được",
        "không đổi gì, không đi được đâu",
        "khong huy dau, toi van den",
        "không hủy đâu, chưa chắc đến",
    ],
)
def test_new_attendance_words_never_write_when_negated_or_unclear(answer: str) -> None:
    """Mỗi từ mới mở rộng ngưỡng ghi CONFIRMED có ca âm tính (`agreement._PARTICLE_WORDS`)."""
    bot, clinic, _ = _at_readback("c_t04_new_words")
    _run(bot, "c_t04_new_words", [answer], start=3)
    assert clinic.writes == []


def test_yes_after_the_reread_confirms() -> None:
    bot, clinic, _ = _at_readback("c_t04s8_story_yes")
    action = _run(bot, "c_t04s8_story_yes", ["dạ hôm đó tôi bận rồi", "vâng"], start=3)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


@pytest.mark.parametrize("answer", ["không thành vấn đề", "nhất định rồi", "tôi sẽ có mặt"])
def test_other_ways_of_agreeing_confirm_in_one_turn(answer: str) -> None:
    bot, clinic, _ = _at_readback("c_t04s8_agree")
    action = _run(bot, "c_t04s8_agree", [answer], start=3)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


def test_not_wanting_to_change_is_not_asked_change_or_cancel() -> None:
    bot, clinic, _ = _at_readback("c_t04s8_nochange")
    action = _run(bot, "c_t04s8_nochange", ["không cần đổi đâu"], start=3)
    assert action.utterance != t.ASK_CHANGE_OR_CANCEL and FACTS in action.utterance
    assert clinic.writes == []


@pytest.mark.parametrize("keep", ["giữ nguyên", "không đổi không hủy gì cả"])
def test_keeping_after_a_refusal_rereads_then_confirms(keep: str) -> None:
    bot, clinic, _ = _at_readback("c_t04s8_keep")
    action = _run(bot, "c_t04s8_keep", ["không", keep], start=3)
    assert action.state == "AWAITING_CONFIRMATION" and FACTS in action.utterance
    assert clinic.writes == []
    action = _run(bot, "c_t04s8_keep", ["vâng"], start=5)
    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


class _FakeSemantic:
    def __init__(self, replies: dict[str, SemanticOutcome]) -> None:
        self._replies = replies

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        return self._replies.get(context.transcript)


def test_model_clinical_advice_transfers_before_attendance_confirmation() -> None:
    line = "thuốc này có cần tiếp tục dùng đến ngày khám không"
    bot, clinic, _ = _at_readback("c_t04_model_clinical")
    bot._extractor._semantic = _FakeSemantic(
        {
            line: SemanticOutcome(
                ReplyKind.QUESTION,
                clinical=ClinicalLevel.ADVICE_REQUEST,
                clinical_span=line,
            )
        }
    )
    action = _run(bot, "c_t04_model_clinical", [line], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "CLINICAL_QUESTION")
    assert _confirm_writes(clinic) == []


def test_a_reason_read_by_the_model_asks_change_or_cancel_without_counting() -> None:
    """AC-3: lý do không đến được là từ chối đến khám, không phải "em chưa hiểu"."""
    line = "dạ hôm đó tôi bận rồi"
    bot, clinic, _ = _at_readback("c_t04s8_sem")
    bot._extractor._semantic = _FakeSemantic(
        {
            line: SemanticOutcome(
                ReplyKind.INFORM_REASON,
                cancel_reason="PATIENT_UNAVAILABLE",
                reason_span="hôm đó tôi bận rồi",
            )
        }
    )
    action = _run(bot, "c_t04s8_sem", [line], start=3)
    assert action.utterance == t.ASK_CHANGE_OR_CANCEL and clinic.writes == []
    ctx = _context(bot, "c_t04s8_sem")
    assert (ctx.unclear_streak, ctx.failed_understandings) == (0, 0)


@pytest.mark.parametrize("source", ["attendance", "intent"])
def test_reason_before_cancel_is_kept_through_confirmation(source: str) -> None:
    bot, clinic, _ = _at_readback("c_reason_before_cancel")
    line = "tuần đó tôi sẽ đi nước ngoài"
    bot._extractor._semantic = _FakeSemantic(
        {
            line: SemanticOutcome(
                ReplyKind.INFORM_REASON,
                cancel_reason="PATIENT_UNAVAILABLE",
                reason_span=line,
            )
        }
    )
    lines = (["không"] if source == "intent" else []) + [line, "hủy giúp tôi"]
    action = _run(bot, "c_reason_before_cancel", lines, start=3)
    assert not action.ended and clinic.writes == []
    # Lý do phải sống qua serialization của session và lời đáp lễ chưa xác nhận.
    action = _run(bot, "c_reason_before_cancel", ["vâng", "đúng, hủy đi"], start=3 + len(lines))
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]


@pytest.mark.parametrize(
    "lines, expected_reason",
    [
        (["hủy giúp tôi vì đắt quá", "đúng, hủy đi"], "COST"),
        (["giữ nguyên lịch", "hủy giúp tôi", "đúng, hủy đi"], "UNSPECIFIED"),
    ],
)
def test_previous_attendance_reason_is_replaced_or_cleared_on_changed_intent(
    lines, expected_reason
):
    bot, clinic, _ = _at_readback("c_reason_lifecycle")
    line = "tuần đó tôi sẽ đi nước ngoài"
    bot._extractor._semantic = _FakeSemantic(
        {
            line: SemanticOutcome(
                ReplyKind.INFORM_REASON,
                cancel_reason="PATIENT_UNAVAILABLE",
                reason_span=line,
            )
        }
    )
    action = _run(bot, "c_reason_lifecycle", [line, *lines], start=3)
    assert action.outcome == "CANCELLED"
    assert clinic.writes == [("apt_00417", "CANCELLED", {"cancel_reason": expected_reason})]


def test_returning_to_attendance_reads_department_before_confirmation() -> None:
    bot, clinic, _ = _at_readback("c_return_readback")
    action = _run(bot, "c_return_readback", ["hủy giúp tôi", "không hủy nữa"], start=3)
    assert "Nội tổng quát" in action.utterance and FACTS in action.utterance
    assert clinic.writes == []
    assert _run(bot, "c_return_readback", ["vâng"], start=5).outcome == "CONFIRMED"


def test_giving_up_a_reschedule_keeps_the_appointment_and_transfers() -> None:
    """PRD R-29 v2.1 (GC-RES-09): bỏ ngang đổi lịch -> giữ lịch cũ, chuyển PATIENT_REQUEST."""
    bot, clinic, _ = _at_readback("c_return_resched")
    action = _run(bot, "c_return_resched", ["tôi muốn đổi lịch", "thôi không đổi nữa"], start=3)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert [w[1] for w in clinic.writes] == ["TRANSFERRED"]


def test_a_statement_at_the_slot_readback_does_not_reschedule() -> None:
    """Cùng lỗi ở câu đọc lại slot: "tôi có việc bận" từng ghi RESCHEDULED."""
    bot, clinic, _ = _at_readback("c_t04s8_slot")
    action = _run(bot, "c_t04s8_slot", ["tôi muốn đổi lịch", "khung 1 được không"], start=3)
    assert _context(bot, "c_t04s8_slot").question.question_id is QuestionId.SLOT_READBACK
    action = _run(bot, "c_t04s8_slot", ["hôm đó tôi có việc bận"], start=5)
    assert not action.ended and clinic.writes == []


# --- T-04 §8: từ khóa CONFIRM khớp nhầm không chặn tầng ngữ nghĩa ---------------------------------

TRIP = "hôm đó tôi sẽ đi công tác"
TRIP_REASON = SemanticOutcome(
    ReplyKind.INFORM_REASON, cancel_reason="PATIENT_UNAVAILABLE", reason_span=TRIP
)


def test_a_trip_mistaken_for_attendance_asks_change_or_cancel_when_the_model_reads_it() -> None:
    bot, clinic, _ = _at_readback("c_t04_trip")
    bot._extractor._semantic = _FakeSemantic({TRIP: TRIP_REASON})
    action = _run(bot, "c_t04_trip", [TRIP], start=3)
    assert action.utterance == t.ASK_CHANGE_OR_CANCEL and clinic.writes == []


def test_without_the_model_the_trip_only_rereads() -> None:
    """R-31: model không trả kết quả thì hỏi đóng và đếm không hiểu, không dùng lại luật."""
    bot, clinic, _ = _at_readback("c_t04_trip_off")
    bot._extractor._semantic = _FakeSemantic({})
    action = _run(bot, "c_t04_trip_off", [TRIP], start=3)
    assert action.utterance == t.CONFIRM_CONFLICT and clinic.writes == []
    assert _context(bot, "c_t04_trip_off").failed_understandings == 1


def test_a_reason_at_change_or_cancel_asks_that_question_again_without_counting() -> None:
    """Q-2: "đổi hay hủy?" -> kể lý do: hỏi lại, lần đầu không tính §1.1.5; sau đó hủy vẫn cần 2 lượt."""
    bot, clinic, _ = _at_readback("c_t04_trip_intent")
    bot._extractor._semantic = _FakeSemantic({TRIP: TRIP_REASON})
    action = _run(bot, "c_t04_trip_intent", ["không", TRIP], start=3)
    assert action.utterance in t.static_choices(t.ASK_CHANGE_OR_CANCEL) and clinic.writes == []
    ctx = _context(bot, "c_t04_trip_intent")
    assert ctx.question.question_id is QuestionId.ASK_INTENT and ctx.question.turn == 4
    assert (ctx.unclear_streak, ctx.failed_understandings) == (1, 0)
    action = _run(bot, "c_t04_trip_intent", ["hủy lịch giúp tôi"], start=5)
    assert _context(bot, "c_t04_trip_intent").question.question_id is QuestionId.CANCEL_RECONFIRM
    assert clinic.writes == []


def test_an_unspecified_reason_at_the_readback_rereads() -> None:
    line = "tôi được nghỉ hôm đó mà"
    bot, clinic, _ = _at_readback("c_t04_offday")
    bot._extractor._semantic = _FakeSemantic(
        {
            line: SemanticOutcome(
                ReplyKind.INFORM_REASON, cancel_reason="UNSPECIFIED", reason_span=line
            )
        }
    )
    action = _run(bot, "c_t04_offday", [line], start=3)
    assert FACTS in action.utterance and action.utterance != t.ASK_CHANGE_OR_CANCEL
    assert clinic.writes == []


# --- QC qc-w6-01: người gọi nói tiếng Anh, vẫn cần xác minh + đọc lại + đồng ý --------------------


def test_english_caller_is_verified_read_back_and_confirmed() -> None:
    """Nguyên văn qc-w6-01 (12/10/2026): ngày sinh ASR ghi bằng chữ; "Yes, I'll be there" là đồng ý."""
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart(call_id="c_w6_01", direction="outbound", appointment_id="apt_00417"))
    lines = ["Hello?", "Nguyen Van A", "March fourteenth, nineteen seventy-eight"]
    summary = _run(bot, "c_w6_01", lines)
    assert summary.state == "AWAITING_INTENT" and FACTS in summary.utterance

    action = _run(bot, "c_w6_01", ["Yes, I'll be there"], start=4)

    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]


class _CountingSemantic(_FakeSemantic):
    def __init__(self, replies: dict[str, SemanticOutcome]) -> None:
        super().__init__(replies)
        self.calls = 0

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        self.calls += 1
        return super().analyze(context)


def test_english_agreement_is_decided_by_rules_without_the_model() -> None:
    """Jev thật đọc "Yes, I'll be there" là CHANGE_INTENT / CONFIRM (thử 12/10/2026), nhưng model không
    được nâng lên AGREE (§8.3.4): lệnh ghi đến từ luật, và câu đã dứt khoát thì không gọi model."""
    line = "Yes, I'll be there"
    bot, clinic, _ = _at_readback("c_w6_01_model")
    model = _CountingSemantic(
        {line: SemanticOutcome(ReplyKind.CHANGE_INTENT, intent=Intent.CONFIRM, intent_span=line)}
    )
    bot._extractor._semantic = model

    action = _run(bot, "c_w6_01_model", [line], start=3)

    assert action.outcome == "CONFIRMED" and clinic.writes == [CONFIRMED_WRITE]
    assert model.calls == 0


def test_english_refusal_asks_change_or_cancel_without_writing() -> None:
    bot, clinic, _ = _at_readback("c_w6_01_no")
    action = _run(bot, "c_w6_01_no", ["No, I can't make it"], start=3)
    assert action.utterance == t.ASK_CHANGE_OR_CANCEL and clinic.writes == []
