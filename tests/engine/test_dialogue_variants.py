"""Biến thể thật: guard, dữ kiện, đồng ý hành động, replay và restart Redis.

Các business test cũ cố định v0. Module này thay fixture đó để selector thật hoạt động;
ma trận v0..v3 ép từng lựa chọn qua cùng orchestrator/guard, không gọi provider trả phí.
"""

from dataclasses import replace
from datetime import date, datetime

import pytest

from callbot.engine import CallEnded, CallerInput, CallStart, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.variants import VARIANT_IDS, choose_variant
from callbot.engine.extraction.schema import VN_TZ, QuestionId
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.utterances import OUTPUT_UNREGISTERED, STATIC_UTTERANCES, bind_ledger
from callbot.engine.session.context import CallContext
from clinic_mock_sim import FakeClinicAPI
from tests.engine.policy.test_output_guard import APPOINTMENT, SLOTS, _ask, _check, _ctx
from tests.engine.test_orchestrator import _context, _inbound, _outbound, _run
from tests.engine.test_reschedule_dialogue import _call, _say
from tests.transports.http.test_calls import _start, _turn

NOW = datetime(2026, 10, 1, 9, tzinfo=VN_TZ)


@pytest.fixture(autouse=True)
def fixed_dialogue_variant():
    """Override fixture ở conftest: dùng selector thật trừ khi test ép một variant."""


@pytest.fixture(params=VARIANT_IDS)
def variant(request, monkeypatch):
    selected = request.param
    monkeypatch.setattr(t, "choose_variant", lambda ctx, group: selected)
    return selected


def test_real_selector_survives_context_roundtrip_and_uses_all_variants():
    ctx = CallContext(call=_outbound("c_variant_roundtrip"), opened_at=NOW)
    seen = []
    for turn in range(4):
        ctx.turn = turn
        restored = CallContext.from_dict(ctx.to_dict())
        actual = choose_variant(ctx, "ASK_DOB")
        assert choose_variant(restored, "ASK_DOB") == actual
        seen.append(actual)
    assert set(seen) == set(VARIANT_IDS)


def test_real_openings_vary_and_alo_uses_the_single_identity_retry():
    bot = create_orchestrator(FakeClinicAPI())
    seen, summaries = set(), set()
    for index in range(40):
        call_id = f"c_variant_opening_{index}"
        opening = bot.start_call(_outbound(call_id))
        seen.add(opening.utterance)
        reply = _run(bot, call_id, ["alo"])
        assert reply.utterance in t.static_choices(t.ASK_NAME_AGAIN)
        assert _context(bot, call_id).failed_understandings == 1
        assert _context(bot, call_id).identity_retries == {"ASK_NAME": 1}
        summary = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"], start=2)
        assert summary.state == "AWAITING_INTENT"
        assert summary.utterance.endswith(t.ASK_ATTENDANCE)
        summaries.add(summary.utterance)
    assert seen == set(t.static_choices(t.GREETING_OUTBOUND))
    assert len(summaries) == 4


def test_catalog_has_four_registered_short_safe_forms_and_freezes_cancel():
    for original, choices in t.STATIC_VARIANTS.items():
        assert len(set(choices)) == 4
        assert choices[0] == original
        for text in choices:
            assert text in STATIC_UTTERANCES
            assert STATIC_UTTERANCES[text].success_outcome is None
            assert len(text) <= 300  # Vbee adapter limit
            assert not any(secret in text.lower() for secret in ("1978", "nguyễn văn a", "9 giờ"))
    for text in (t.CANCEL_RECONFIRM, t.CANCEL_CHOICE, t.CANCEL_REASON_NOTED, *t.DONE_SAFE.values()):
        if text == t.TRANSFER or text == t.GOODBYE_UNREACHABLE:
            continue  # normal handoff/closing vary; safety fallback itself remains v0
        assert t.static_choices(text) == (text,)


@pytest.mark.parametrize(
    "render,ending",
    [
        (t.appointment_summary, t.ASK_ATTENDANCE),
        (t.attendance_readback, "Anh chị đồng ý chứ ạ?"),
        (t.attendance_reread, t.ASK_ATTENDANCE),
        (t.keep_appointment, t.ASK_ATTENDANCE),
    ],
)
def test_every_attendance_variant_is_guarded_and_has_the_same_facts(variant, render, ending):
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = render(ctx, APPOINTMENT, variant=variant)
    assert "Nội tổng quát" in text
    assert t.attendance_facts(APPOINTMENT) in text
    assert text.endswith(ending) and len(text) <= 300
    action = _ask(ctx, QuestionId.CONFIRM_READBACK, text, action="CONFIRM")
    assert _check(action, ctx, ledger=ledger).ok

    # Modifier cannot rewrite the factual part while keeping a valid render record.
    forged = replace(action, utterance=text.replace("9 giờ", "10 giờ"))
    assert not _check(forged, ctx, ledger=ledger).ok
    with pytest.raises(SevereFailureBlocked) as failure:
        render(_ctx(verified=False), APPOINTMENT, variant=variant)
    assert failure.value.code == "SF-03"


@pytest.mark.parametrize("action_name", ["BOOK", "RESCHEDULE"])
@pytest.mark.parametrize("render", [t.slot_readback, t.slot_offer_readback])
def test_every_slot_readback_keeps_selected_slot_and_consent(variant, action_name, render):
    ctx, ledger = _ctx(), []
    ctx.pending_action = action_name
    ctx.selected_slot_id = SLOTS[0]["slot_id"]
    with bind_ledger(ledger):
        text = render(ctx, SLOTS[0], action_name, variant=variant)
    assert "10 giờ sáng" in text and "thứ Tư ngày 14 tháng 10" in text
    ending = (
        "Anh chị đồng ý chứ ạ?"
        if render is t.slot_readback
        else f"Anh chị {'đặt' if action_name == 'BOOK' else 'đổi sang'} giờ đó nhé ạ?"
    )
    assert text.endswith(ending) and len(text) <= 300
    action = _ask(
        ctx, QuestionId.SLOT_READBACK, text, action=action_name, slot_id=ctx.selected_slot_id
    )
    assert _check(action, ctx, ledger=ledger).ok
    ctx.selected_slot_id = SLOTS[1]["slot_id"]
    assert not _check(action, ctx, ledger=ledger).ok


def test_unregistered_variant_is_rejected_before_render():
    with pytest.raises(SevereFailureBlocked) as failure:
        t.attendance_readback(_ctx(), APPOINTMENT, variant="invented")
    assert failure.value.code == OUTPUT_UNREGISTERED


def test_all_offers_keep_prefix_page_count_and_invitation(variant):
    ctx = _ctx()
    with bind_ledger([]):
        normal = t.offer_slots(ctx, SLOTS, t.SLOT_TAKEN, remaining=3, variant=variant)
        full = t.offer_slots(ctx, SLOTS, full_date=date(2026, 10, 13), variant=variant)
        invited = t.offer_slots(ctx, SLOTS, invite="BOOK", variant=variant)
    assert normal.startswith(t.SLOT_TAKEN) and normal.count("Dạ") == 1
    assert "Ngoài ra còn 3 khung khác." in normal
    assert "thứ Ba ngày 13 tháng 10 đã kín lịch" in full
    assert invited.endswith("Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ?")
    for text in (normal, full, invited):
        assert "khung 1 là 10 giờ sáng" in text and "khung 2 là 2 giờ 30 chiều" in text
        assert len(text) <= 300


def test_confirm_after_repeat_silence_and_worker_restart_writes_once(variant):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_variant_confirm"))
    readback = _run(bot, "c_variant_confirm", ["Nguyễn Văn A", "14/03/1978"])
    assert readback.utterance == t.appointment_summary(
        _context(bot, "c_variant_confirm"), clinic.appointments["apt_00417"], variant=variant
    )
    assert clinic.writes == []
    repeated = _run(bot, "c_variant_confirm", ["nhắc lại giúp tôi"], start=3)
    assert repeated.utterance == readback.utterance
    silent = _run(bot, "c_variant_confirm", [None], start=4)
    assert silent.utterance == t.silence_reprompt(readback.utterance)
    assert _context(bot, "c_variant_confirm").question.text == readback.utterance
    restarted = create_orchestrator(clinic, store=bot.sessions.store)
    assert (
        restarted.handle_turn("c_variant_confirm", CallerInput(turn=4, text=None, silence_ms=2000))
        == silent
    )
    agree = CallerInput(turn=5, text="vâng, tôi đến được")
    done = restarted.handle_turn("c_variant_confirm", agree)
    assert done.outcome == "CONFIRMED"
    # Kết thúc xóa nội dung phiên theo chính sách hiện có; retry không được ghi lần hai.
    with pytest.raises(CallEnded):
        restarted.handle_turn("c_variant_confirm", agree)
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def test_cancel_requires_unchanged_second_confirmation(variant):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_variant_cancel"))
    asked = _run(bot, "c_variant_cancel", ["Nguyễn Văn A", "14/03/1978", "tôi muốn hủy lịch"])
    assert asked.utterance == t.CANCEL_RECONFIRM and clinic.writes == []
    clarified = _run(bot, "c_variant_cancel", ["vâng"], start=4)
    assert clarified.utterance == t.CANCEL_CHOICE and clinic.writes == []
    done = _run(bot, "c_variant_cancel", ["hủy lịch giúp tôi"], start=5)
    assert done.outcome == "CANCELLED"
    assert len(clinic.writes) == 1


def test_slot_paging_and_confirmation_write_only_the_selected_slot(variant):
    clinic, bot, page = _call("c_variant_slot", "Tôi đổi sang buổi chiều được không?")
    assert page.state == "OFFERING_SLOTS" and "Ngoài ra còn 4 khung khác" in page.utterance
    readback = _say(bot, "c_variant_slot", "khung 2")
    assert readback.utterance.endswith("Anh chị đồng ý chứ ạ?")
    assert clinic.writes == []
    done = _say(bot, "c_variant_slot", "đồng ý")
    assert done.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


def test_inbound_still_verifies_then_books_exactly_one_appointment(variant):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    bot.start_call(_inbound("c_variant_book"))
    asked = _run(bot, "c_variant_book", ["Nguyễn Văn A", "14/03/1978"])
    assert asked.utterance in t.static_choices(t.ASK_INTENT_INBOUND)
    offered = _run(bot, "c_variant_book", ["tôi muốn đặt lịch", "khung 1"], start=3)
    assert offered.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    booked = _run(bot, "c_variant_book", ["đồng ý"], start=5)
    assert booked.outcome == "BOOKED" and len(clinic.writes) == 1


def test_unknown_inbound_opening_never_claims_identity_or_appointment(variant):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    opening = bot.start_call(
        CallStart(call_id="c_variant_unknown", direction="inbound", caller_number="0999999999")
    )
    assert opening.utterance in t.static_choices(t.GREETING_HANDOFF_INBOUND)
    assert t.AI_DISCLOSURE in opening.utterance and "?" not in opening.utterance
    action = _run(bot, "c_variant_unknown", ["alo"])
    assert action.outcome == "TRANSFERRED" and clinic.writes == []


def test_audio_transport_sends_the_selected_text_to_tts_and_serves_audio(variant, client, clinic):
    response = _start(client, "c_variant_audio", mode="audio")
    assert response.status_code == 200
    replies = [response.json()]
    for turn, transcript in enumerate(
        ["Nguyễn Văn A", "14/03/1978", "nhắc lại giúp tôi", "vâng, tôi đến được"], start=1
    ):
        client.app.state.speech.asr.transcript = transcript
        response = _turn(
            client, "c_variant_audio", turn, None, audio_url="https://harness/clip.wav"
        )
        assert response.status_code == 200
        replies.append(response.json())
    assert replies[2]["utterance"] == replies[3]["utterance"]
    assert client.app.state.speech.tts.spoken == [reply["utterance"] for reply in replies]
    for reply in replies:
        audio = client.get(reply["audio_url"])
        assert audio.status_code == 200 and audio.content.startswith(b"RIFF")
    assert replies[-1]["outcome"] == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
