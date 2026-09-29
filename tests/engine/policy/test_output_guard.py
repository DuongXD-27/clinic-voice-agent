"""R-01 Output Guard — luật OG-0..OG-6 và receipt gate dạng hàm thuần.

Dữ liệu khớp seed Listing 3: apt_00417 lúc 9 giờ sáng 14/10 tại cl_vinmec, slot_aa01 (10:00),
slot_91d2 (14:30).
"""

import ast
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytest

from callbot.engine.dialogue import templates as t
from callbot.engine.errors import WriteOutcomeUnknown
from callbot.engine.extraction.schema import VN_TZ, QuestionId
from callbot.engine.journal import ClinicCommand, JournalEntry
from callbot.engine.policy import output_guard
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.output_guard import GuardInput, Receipt
from callbot.engine.policy.sources import SourceRegistry
from callbot.engine.policy.utterances import (
    OUTPUT_UNREGISTERED,
    RENDERERS,
    STATIC_UTTERANCES,
    RenderRecord,
    SourceRef,
    bind_ledger,
)
from callbot.engine.session.context import CallContext, Question
from callbot.engine.types import BotAction, CallStart

APPOINTMENT: dict[str, Any] = {
    "appointment_id": "apt_00417",
    "status": "SCHEDULED",
    "version": 1,
    "starts_at": "2026-10-14T09:00:00+07:00",
    "clinic_id": "cl_vinmec",
    "department": "Nội tổng quát",
}
SLOTS: list[dict[str, Any]] = [
    {"slot_id": "slot_aa01", "starts_at": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "slot_91d2", "starts_at": "2026-10-14T14:30:00+07:00"},
]
TURN = 5


def _ctx(
    *,
    verified: bool = True,
    slots: Optional[list[dict[str, Any]]] = None,
    question: Optional[Question] = None,
) -> CallContext:
    return CallContext(
        call=CallStart(call_id="c_guard", direction="outbound", appointment_id="apt_00417"),
        opened_at=datetime(2026, 10, 1, 9, tzinfo=VN_TZ),
        state="AWAITING_INTENT" if verified else "AWAITING_IDENTITY",
        turn=TURN,
        identity_step="VERIFIED" if verified else "ASK_NAME",
        identity_lookup="LOADED",
        patient_id="p_1" if verified else None,
        question=question,
        slots=[dict(slot) for slot in (SLOTS if slots is None else slots)],
    )


def _sources(ctx: CallContext) -> SourceRegistry:
    registry = SourceRegistry(ctx.slots)
    registry.record_appointment(APPOINTMENT)
    return registry


def _check(
    action: BotAction,
    ctx: CallContext,
    *,
    ledger: Optional[list[RenderRecord]] = None,
    sources: Optional[SourceRegistry] = None,
    prior: Optional[Question] = None,
    receipt: Optional[Receipt] = None,
) -> output_guard.GuardVerdict:
    output_guard.normalize_question(ctx, action)
    return output_guard.check(
        GuardInput(
            action,
            ctx,
            prior,
            ledger or [],
            sources if sources is not None else _sources(ctx),
            receipt,
        )
    )


def _ask(ctx: CallContext, question_id: QuestionId, text: str, **kwargs: Any) -> BotAction:
    ctx.question = Question(question_id, text, ctx.turn, **kwargs)
    return BotAction(text, ctx.state)


def _receipt(operation: str, payload: dict[str, Any], result: dict[str, Any]) -> Receipt:
    endpoint = "/appointments" if operation == "book" else f"/appointments/apt_00417/{operation}"
    command = ClinicCommand(operation, endpoint, payload, 1, f"c_guard:{TURN}:{operation}")
    return Receipt(command, result)


CONFIRMED_RECEIPT = _receipt("confirm", {}, {**APPOINTMENT, "status": "CONFIRMED", "version": 2})


def _blocked(verdict: output_guard.GuardVerdict, rule: str, code: str) -> None:
    assert (verdict.ok, verdict.rule, verdict.code) == (False, rule, code)


# --- OG-0: allow-list nguồn gốc câu thoại ---------------------------------------------------


@pytest.mark.parametrize(
    "utterance",
    [
        "Lịch khám của anh chị ở khoa Tim mạch ạ.",  # không ngày giờ vẫn bị chặn
        "Lịch khám của anh chị là 9 giờ sáng ngày 14 tháng 10 ạ.",
    ],
)
def test_handwritten_utterance_is_blocked(utterance: str) -> None:
    ctx = _ctx()
    _blocked(_check(BotAction(utterance, ctx.state), ctx), "OG-0", OUTPUT_UNREGISTERED)


def test_registered_forms_pass() -> None:
    # Hằng tĩnh
    ctx = _ctx()
    assert _check(BotAction(t.HOLD, ctx.state), ctx).ok

    # Renderer có trong ledger của lượt
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = t.attendance_readback(ctx, APPOINTMENT)
    action = _ask(ctx, QuestionId.CONFIRM_READBACK, text, action="CONFIRM")
    assert _check(action, ctx, ledger=ledger).ok

    # Đọc lại / nhắc im lặng câu hỏi của lượt trước
    prior = Question(QuestionId.CONFIRM_READBACK, text, TURN - 1, action="CONFIRM")
    for utterance in (text, t.silence_reprompt(text)):
        ctx = _ctx(question=replace(prior, turn=TURN))
        assert _check(BotAction(utterance, ctx.state), ctx, prior=prior).ok


def test_success_constant_as_slot_prefix_is_rejected() -> None:
    """Prefix chỉ nhận SLOT_PREFIXES: "đã xác nhận" làm prefix sẽ lọt kiểm tra lời báo thành công."""
    ctx = _ctx()
    ctx.presented_slot_ids = ["slot_aa01"]
    with pytest.raises(SevereFailureBlocked) as exc:
        t.offer_slots(ctx, SLOTS[:1], t.DONE_SAFE["CONFIRMED"])
    assert exc.value.code == OUTPUT_UNREGISTERED

    # Record giả mạo (không qua decorator) cũng bị guard chặn
    text = RENDERERS["OFFER_SLOTS"].render(ctx, SLOTS[:1], t.DONE_SAFE["CONFIRMED"])
    forged = RenderRecord(
        "OFFER_SLOTS",
        (SourceRef("slots", "SLOT", "slot_aa01"),),
        {"prefix": t.DONE_SAFE["CONFIRMED"]},
        text,
    )
    action = _ask(ctx, QuestionId.OFFER_SLOTS, text, action="RESCHEDULE")
    _blocked(_check(action, ctx, ledger=[forged]), "OG-0", OUTPUT_UNREGISTERED)


def test_silence_reprompt_only_wraps_the_prior_question() -> None:
    prior = Question(QuestionId.ASK_DOB, t.ASK_DOB, TURN - 1)
    ctx, ledger = _ctx(question=replace(prior, turn=TURN)), []
    with bind_ledger(ledger):
        other = t.silence_reprompt("Lịch khám của anh chị ở khoa Tim mạch.")
    _blocked(
        _check(BotAction(other, ctx.state), ctx, ledger=ledger, prior=prior),
        "OG-0",
        OUTPUT_UNREGISTERED,
    )


def test_without_ledger_templates_render_unchanged_and_are_pure() -> None:
    ctx, ledger = _ctx(), []
    plain = t.attendance_readback(ctx, APPOINTMENT)
    with bind_ledger(ledger):
        recorded = t.attendance_readback(ctx, APPOINTMENT)
    assert plain == recorded == t.attendance_readback(ctx, APPOINTMENT)
    assert [(item.template_id, item.refs) for item in ledger] == [
        ("ATTENDANCE_READBACK", (SourceRef("appointment", "APPOINTMENT", "apt_00417"),))
    ]


# --- OG-1: SF-03 ------------------------------------------------------------------------------


def test_disclosing_render_before_verification_is_blocked() -> None:
    ledger: list[RenderRecord] = []
    with bind_ledger(ledger):
        text = t.appointment_summary(_ctx(), APPOINTMENT)
    ctx = _ctx(verified=False)
    _blocked(_check(BotAction(text, ctx.state), ctx, ledger=ledger), "OG-1", "SF-03")


def test_disclosing_render_on_voicemail_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = t.attendance_readback(ctx, APPOINTMENT)
    action = BotAction(
        text, "ENDED", ended=True, outcome="UNREACHABLE", unreachable_reason="SILENCE"
    )
    _blocked(_check(action, ctx, ledger=ledger), "OG-1", "SF-03")


@pytest.mark.parametrize("wrap", [False, True])
def test_rereading_a_dynamic_question_on_voicemail_is_blocked(wrap: bool) -> None:
    """Ledger chỉ sống trong lượt: câu hỏi động của lượt trước bị coi là lộ lịch (fail-closed)."""
    text = t.attendance_readback(_ctx(), APPOINTMENT)
    prior = Question(QuestionId.CONFIRM_READBACK, text, TURN - 1, action="CONFIRM")
    utterance = t.silence_reprompt(text) if wrap else text
    ctx = _ctx(question=prior)
    action = BotAction(
        utterance, "ENDED", ended=True, outcome="UNREACHABLE", unreachable_reason="VOICEMAIL"
    )
    _blocked(_check(action, ctx, prior=prior), "OG-1", "SF-03")


def test_rereading_a_static_question_on_voicemail_passes() -> None:
    prior = Question(QuestionId.ASK_DOB, t.ASK_DOB, TURN - 1)
    ctx = _ctx(question=prior)
    for utterance in (t.ASK_DOB, t.silence_reprompt(t.ASK_DOB)):
        action = BotAction(
            utterance, "ENDED", ended=True, outcome="UNREACHABLE", unreachable_reason="SILENCE"
        )
        assert _check(action, ctx, prior=prior).ok


def test_every_question_renderer_is_declared_as_disclosing() -> None:
    """Giả định fail-closed của metadata đọc lại (§3.2): renderer đưa vào ask() đều lộ lịch."""
    for template_id, spec in RENDERERS.items():
        if spec.success_outcome is None:
            assert spec.discloses, template_id
    assert not any(spec.discloses for spec in STATIC_UTTERANCES.values())


# --- OG-2 / OG-3: nguồn dữ liệu và render lại -----------------------------------------------


def test_unknown_appointment_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    other = {**APPOINTMENT, "appointment_id": "apt_other"}
    sources = _sources(ctx)
    sources.record_appointment(other)
    with bind_ledger(ledger):
        text = t.attendance_readback(ctx, other)
    action = _ask(ctx, QuestionId.CONFIRM_READBACK, text, action="CONFIRM")
    _blocked(_check(action, ctx, ledger=ledger, sources=sources), "OG-2", "SF-01")


def test_slot_outside_snapshot_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    ghost = {"slot_id": "slot_ghost", "starts_at": "2026-10-15T08:00:00+07:00"}
    ctx.pending_action, ctx.selected_slot_id = "RESCHEDULE", "slot_ghost"
    with bind_ledger(ledger):
        text = t.slot_readback(ctx, ghost)
    action = _ask(ctx, QuestionId.SLOT_READBACK, text, action="RESCHEDULE", slot_id="slot_ghost")
    _blocked(_check(action, ctx, ledger=ledger), "OG-3", "SF-02")


def test_real_slot_id_with_edited_time_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    ctx.pending_action, ctx.selected_slot_id = "RESCHEDULE", "slot_aa01"
    forged = {"slot_id": "slot_aa01", "starts_at": "2026-10-14T07:00:00+07:00"}
    with bind_ledger(ledger):
        text = t.slot_readback(ctx, forged)
    action = _ask(ctx, QuestionId.SLOT_READBACK, text, action="RESCHEDULE", slot_id="slot_aa01")
    _blocked(_check(action, ctx, ledger=ledger), "OG-3", "SF-02")


def test_in_place_edit_of_ctx_slot_is_blocked() -> None:
    """Sửa dict thật trong `ctx.slots` (không phải dict giả riêng): dữ liệu render và `ctx` cùng sai."""
    ctx, ledger = _ctx(), []
    sources = _sources(ctx)  # snapshot đầu lượt
    ctx.pending_action, ctx.selected_slot_id = "RESCHEDULE", "slot_aa01"
    slot = ctx.find_slot("slot_aa01")
    slot["starts_at"] = "2026-10-14T07:00:00+07:00"
    with bind_ledger(ledger):
        text = t.slot_readback(ctx, slot)
    action = _ask(ctx, QuestionId.SLOT_READBACK, text, action="RESCHEDULE", slot_id="slot_aa01")
    _blocked(_check(action, ctx, ledger=ledger, sources=sources), "OG-3", "SF-02")


def test_in_place_edit_of_list_open_slots_result_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    sources = _sources(ctx)
    sources.record_slots(ctx.slots)  # SourceRecorder chụp ngay khi Gateway trả về
    returned = list(ctx.slots)  # Gateway trả shallow copy: cùng dict với ctx.slots
    returned[1]["starts_at"] = "2026-10-14T07:00:00+07:00"
    ctx.presented_slot_ids = ["slot_aa01", "slot_91d2"]
    ctx.pending_action = "RESCHEDULE"
    with bind_ledger(ledger):
        text = t.offer_slots(ctx, returned)
    action = _ask(ctx, QuestionId.OFFER_SLOTS, text, action="RESCHEDULE")
    _blocked(_check(action, ctx, ledger=ledger, sources=sources), "OG-3", "SF-02")


def test_appointment_edited_after_read_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    appointment = dict(APPOINTMENT)
    sources = _sources(ctx)
    appointment["starts_at"] = "2026-10-20T09:00:00+07:00"
    with bind_ledger(ledger):
        text = t.attendance_readback(ctx, appointment)
    action = _ask(ctx, QuestionId.CONFIRM_READBACK, text, action="CONFIRM")
    _blocked(_check(action, ctx, ledger=ledger, sources=sources), "OG-3", "SF-02")


def test_rereading_offer_whose_slots_are_gone_is_blocked() -> None:
    ctx = _ctx()
    ctx.pending_action, ctx.presented_slot_ids = "RESCHEDULE", ["slot_aa01", "slot_91d2"]
    text = t.offer_slots(ctx, SLOTS)
    prior = Question(QuestionId.OFFER_SLOTS, text, TURN - 1, action="RESCHEDULE")
    ctx = _ctx(slots=SLOTS[:1], question=replace(prior, turn=TURN))
    ctx.pending_action, ctx.presented_slot_ids = "RESCHEDULE", ["slot_aa01", "slot_91d2"]
    _blocked(_check(BotAction(text, ctx.state), ctx, prior=prior), "OG-3", "SF-02")


def test_offer_of_unpresented_slot_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    ctx.pending_action, ctx.presented_slot_ids = "RESCHEDULE", ["slot_aa01"]
    with bind_ledger(ledger):
        text = t.offer_slots(ctx, SLOTS)
    action = _ask(ctx, QuestionId.OFFER_SLOTS, text, action="RESCHEDULE")
    _blocked(_check(action, ctx, ledger=ledger), "OG-3", "SF-02")


# --- OG-4: SF-04 --------------------------------------------------------------------------


def test_clinical_advice_is_blocked() -> None:
    ctx = _ctx()
    STATIC_UTTERANCES.setdefault(
        "Dạ, anh chị nên uống thuốc hạ sốt ạ.",
        STATIC_UTTERANCES[t.HOLD],  # giả như ai đó đăng ký nhầm một câu tư vấn
    )
    try:
        verdict = _check(BotAction("Dạ, anh chị nên uống thuốc hạ sốt ạ.", ctx.state), ctx)
    finally:
        del STATIC_UTTERANCES["Dạ, anh chị nên uống thuốc hạ sốt ạ."]
    _blocked(verdict, "OG-4", "SF-04")


def test_no_registered_utterance_trips_the_clinical_markers() -> None:
    ctx = _ctx()
    ctx.pending_action, ctx.presented_slot_ids, ctx.selected_slot_id = (
        "RESCHEDULE",
        ["slot_aa01", "slot_91d2"],
        "slot_aa01",
    )
    rendered = [
        t.appointment_summary(ctx, APPOINTMENT),
        t.attendance_readback(ctx, APPOINTMENT),
        t.attendance_reread(ctx, APPOINTMENT),
        t.confirmed(ctx, APPOINTMENT),
        t.keep_appointment(ctx, APPOINTMENT),
        *(t.offer_slots(ctx, SLOTS, prefix, 2) for prefix in t.SLOT_PREFIXES),
        *(t.slot_offer_readback(ctx, SLOTS[0], action) for action in t.SLOT_ACTIONS),
        *(t.slot_readback(ctx, SLOTS[0], action) for action in t.SLOT_ACTIONS),
        *(t.slot_readback_da(ctx, SLOTS[0], action) for action in t.SLOT_ACTIONS),
        t.cancelled_done(),
        t.rescheduled_done(ctx, SLOTS[0]),
        t.booked_done(ctx, SLOTS[0]),
        t.silence_reprompt(t.ASK_DOB),
    ]
    for utterance in [*STATIC_UTTERANCES, *rendered]:
        output_guard._clinical(utterance)  # không raise


# --- OG-5: lời báo thành công --------------------------------------------------------------


def _finish(text: str, outcome: str) -> BotAction:
    return BotAction(text, "ENDED", ended=True, outcome=outcome)  # type: ignore[arg-type]


def test_confirmed_without_receipt_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    written = {**APPOINTMENT, "status": "CONFIRMED"}
    with bind_ledger(ledger):
        text = t.confirmed(ctx, written)
    _blocked(
        _check(_finish(text, "CONFIRMED"), ctx, ledger=ledger), "OG-5", "OUTPUT_UNPROVEN_SUCCESS"
    )
    _blocked(
        _check(_finish(t.DONE_SAFE["CONFIRMED"], "CONFIRMED"), ctx),
        "OG-5",
        "OUTPUT_UNPROVEN_SUCCESS",
    )


def test_confirmed_with_receipt_passes() -> None:
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = t.confirmed(ctx, dict(CONFIRMED_RECEIPT.result))
    assert _check(_finish(text, "CONFIRMED"), ctx, ledger=ledger, receipt=CONFIRMED_RECEIPT).ok


def test_success_outcome_needs_a_success_template() -> None:
    ctx = _ctx()
    _blocked(
        _check(_finish(t.TRANSFER, "CONFIRMED"), ctx, receipt=CONFIRMED_RECEIPT),
        "OG-5",
        "OUTPUT_UNPROVEN_SUCCESS",
    )


def test_confirmed_render_of_another_appointment_is_blocked() -> None:
    ctx, ledger = _ctx(), []
    receipt = replace(
        CONFIRMED_RECEIPT,
        command=replace(CONFIRMED_RECEIPT.command, endpoint="/appointments/apt_other/confirm"),
    )
    with bind_ledger(ledger):
        text = t.confirmed(ctx, dict(receipt.result))
    _blocked(
        _check(_finish(text, "CONFIRMED"), ctx, ledger=ledger, receipt=receipt),
        "OG-5",
        "OUTPUT_UNPROVEN_SUCCESS",
    )


def test_rescheduled_says_changed_and_is_bound_to_the_written_slot() -> None:
    receipt = _receipt(
        "reschedule",
        {"new_slot_id": "slot_aa01", "requested_by": "PATIENT"},
        {**APPOINTMENT, "status": "RESCHEDULED", "new_slot_id": "slot_aa01"},
    )
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        written_slot = t.rescheduled_done(ctx, SLOTS[0])
        other_slot = t.rescheduled_done(ctx, SLOTS[1])  # slot_91d2 cũng có nguồn
    assert "đã đổi lịch" in written_slot
    assert _check(_finish(written_slot, "RESCHEDULED"), ctx, ledger=ledger, receipt=receipt).ok
    _blocked(
        _check(_finish(other_slot, "RESCHEDULED"), _ctx(), ledger=ledger, receipt=receipt),
        "OG-5",
        "OUTPUT_UNPROVEN_SUCCESS",
    )


def test_booked_render_of_another_slot_is_blocked() -> None:
    receipt = _receipt(
        "book",
        {"patient_id": "p_1", "slot_id": "slot_aa01"},
        {"appointment_id": "apt_new", "status": "BOOKED"},
    )
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = t.booked_done(ctx, SLOTS[1])
    _blocked(
        _check(_finish(text, "BOOKED"), ctx, ledger=ledger, receipt=receipt),
        "OG-5",
        "OUTPUT_UNPROVEN_SUCCESS",
    )


_SUCCESS_PHRASES = {
    "đã xác nhận": "CONFIRMED",
    "đã hủy": "CANCELLED",
    "đã đổi lịch": "RESCHEDULED",
    "đã đặt lịch": "BOOKED",
}


def _claimed_outcomes(text: str) -> set[str]:
    lowered = text.lower()
    return {
        outcome
        for phrase, outcome in _SUCCESS_PHRASES.items()
        if re.search(rf"(?<!chưa ){re.escape(phrase)}", lowered)
    }


def test_success_phrases_match_declared_success_outcome() -> None:
    """Câu nói "đã xác nhận / đã hủy / đã đổi lịch / đã đặt lịch" phải khai đúng `success_outcome`."""
    for text, spec in STATIC_UTTERANCES.items():
        claimed = _claimed_outcomes(text)
        assert claimed == ({spec.success_outcome} if spec.success_outcome else set()), text
    ctx = _ctx()
    samples = {
        "CONFIRMED_DONE": t.confirmed(ctx, APPOINTMENT),
        "CANCELLED_DONE": t.cancelled_done(),
        "RESCHEDULED_DONE": t.rescheduled_done(ctx, SLOTS[0]),
        "BOOKED_DONE": t.booked_done(ctx, SLOTS[0]),
    }
    for template_id, text in samples.items():
        assert _claimed_outcomes(text) == {RENDERERS[template_id].success_outcome}, template_id
    for template_id, spec in RENDERERS.items():
        if spec.success_outcome is not None:
            assert template_id in samples


# --- OG-6: toàn vẹn trạng thái trước commit ------------------------------------------------


def test_in_place_slot_edit_without_render_is_blocked() -> None:
    ctx = _ctx()
    sources = _sources(ctx)
    ctx.slots[0]["starts_at"] = "2026-10-14T07:00:00+07:00"
    _blocked(_check(BotAction(t.HOLD, ctx.state), ctx, sources=sources), "OG-6", "SF-02")


def test_question_text_changed_after_ask_is_blocked() -> None:
    ctx = _ctx()
    action = _ask(ctx, QuestionId.ASK_INTENT, t.ASK_CHANGE_OR_CANCEL)
    ctx.question = replace(ctx.question, text=t.CANCEL_RECONFIRM)
    _blocked(_check(action, ctx), "OG-6", OUTPUT_UNREGISTERED)


def test_old_question_edited_without_new_ask_is_blocked() -> None:
    prior = Question(QuestionId.ASK_INTENT, t.ASK_CHANGE_OR_CANCEL, TURN - 1)
    ctx = _ctx(question=replace(prior, text=t.CANCEL_RECONFIRM))
    _blocked(_check(BotAction(t.HOLD, ctx.state), ctx, prior=prior), "OG-6", OUTPUT_UNREGISTERED)


def test_question_state_cases_that_must_pass() -> None:
    prior = Question(QuestionId.ASK_DOB, t.ASK_DOB, TURN - 1)
    # Nhắc im lặng: câu hỏi hỏi lại ở lượt này, giữ nguyên text
    ctx = _ctx(question=replace(prior, turn=TURN))
    assert _check(BotAction(t.silence_reprompt(t.ASK_DOB), ctx.state), ctx, prior=prior).ok
    # Không đổi: HOLD / em chưa hiểu
    ctx = _ctx(question=prior)
    assert _check(BotAction(t.HOLD, ctx.state), ctx, prior=prior).ok
    # Im lặng khi chưa có câu hỏi nào
    ctx = _ctx(question=None)
    assert _check(BotAction(t.SILENCE, ctx.state), ctx).ok
    # Hỏi mới rồi Policy chuyển máy: câu chưa phát bị bỏ khi chuẩn hóa
    ctx = _ctx(question=prior)
    _ask(ctx, QuestionId.ASK_DOB, t.ASK_DOB_AGAIN)
    transfer = BotAction(
        t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason="NOT_UNDERSTOOD"
    )
    assert _check(transfer, ctx, prior=prior).ok
    assert ctx.question is None


# --- Lời mở đầu ------------------------------------------------------------------------------


def test_opening_must_be_a_non_disclosing_constant() -> None:
    ctx = _ctx(verified=False, slots=[])
    ctx.turn = 0
    assert output_guard.check_opening(_ask(ctx, QuestionId.ASK_NAME, t.GREETING_OUTBOUND), ctx).ok
    ctx.question = None
    assert output_guard.check_opening(
        BotAction(t.GREETING_HANDOFF_INBOUND, "AWAITING_IDENTITY"), ctx
    ).ok
    raw = BotAction("Lịch khám của anh chị lúc 9 giờ", "AWAITING_IDENTITY")
    _blocked(output_guard.check_opening(raw, ctx), "OG-0", OUTPUT_UNREGISTERED)
    ended = BotAction(t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED")
    assert not output_guard.check_opening(ended, ctx).ok


# --- Receipt gate ----------------------------------------------------------------------------


def _entry(operation: str, status: str, result: Optional[dict[str, Any]] = None) -> JournalEntry:
    command = ClinicCommand(
        operation,
        f"/appointments/apt_00417/{operation}",
        {"transfer_reason": "SYSTEM_ERROR"} if operation == "transfer" else {},
        1,
        f"c_guard:{TURN}:{operation}",
    )
    return JournalEntry(command, status, result)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["PENDING", "UNKNOWN"])
def test_gate_unsettled_write_requires_reconciliation(status: str) -> None:
    with pytest.raises(WriteOutcomeUnknown):
        output_guard.receipt_gate([_entry("confirm", status)])


def test_gate_two_successes_require_reconciliation() -> None:
    entries = [
        _entry("confirm", "SUCCEEDED", {"status": "CONFIRMED"}),
        _entry("transfer", "SUCCEEDED", {"status": "TRANSFERRED"}),
    ]
    with pytest.raises(WriteOutcomeUnknown):
        output_guard.receipt_gate(entries)


def test_gate_success_with_wrong_status_requires_reconciliation() -> None:
    with pytest.raises(WriteOutcomeUnknown):
        output_guard.receipt_gate([_entry("reschedule", "SUCCEEDED", {"status": "SCHEDULED"})])


def test_gate_failed_then_succeeded_uses_the_success() -> None:
    entries = [
        _entry("unreachable", "FAILED"),
        _entry("transfer", "SUCCEEDED", {"status": "TRANSFERRED"}),
    ]
    receipt = output_guard.receipt_gate(entries)
    assert receipt is not None and receipt.outcome == "TRANSFERRED"
    summary = output_guard.summarize_writes(entries)
    assert (summary.attempted, summary.succeeded, summary.operation) == (2, 1, "transfer")
    assert summary.status_match is True


def test_gate_without_success_allows_fallback() -> None:
    assert output_guard.receipt_gate([]) is None
    assert output_guard.receipt_gate([_entry("unreachable", "FAILED")]) is None


def test_action_must_close_with_the_receipt_outcome_and_reason() -> None:
    receipt = output_guard.receipt_gate(
        [_entry("transfer", "SUCCEEDED", {"status": "TRANSFERRED"})]
    )
    assert receipt is not None
    safe = output_guard.safe_action(receipt)
    assert (safe.utterance, safe.ended, safe.state, safe.transfer_reason) == (
        t.TRANSFER,
        True,
        "ENDED",
        "SYSTEM_ERROR",
    )
    assert output_guard.matches_receipt(safe, receipt)
    assert not output_guard.matches_receipt(
        replace(safe, transfer_reason="PATIENT_REQUEST"), receipt
    )
    assert not output_guard.matches_receipt(replace(safe, ended=False), receipt)
    assert not output_guard.matches_receipt(replace(safe, state="AWAITING_INTENT"), receipt)


# --- Tĩnh: Dialogue không tự viết câu thoại ---------------------------------------------------


def test_dialogue_never_builds_bot_action_from_a_literal() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "callbot" / "engine" / "dialogue"
    offenders = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BotAction"):
                continue
            utterance = (
                node.args[0]
                if node.args
                else next((kw.value for kw in node.keywords if kw.arg == "utterance"), None)
            )
            if isinstance(utterance, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
