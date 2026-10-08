"""Biến thể thật: guard, dữ kiện, đồng ý hành động, replay và restart Redis.

Các business test cũ ưu tiên v0. Module này dùng selector thật;
nhóm tĩnh kiểm v0..v2, đề xuất slot kiểm v0..v3; không gọi provider trả phí.
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
    monkeypatch.setattr(
        t,
        "choose_variant",
        lambda ctx, group, variants=VARIANT_IDS: selected if selected in variants else variants[0],
    )
    return selected


@pytest.mark.parametrize("variants", [VARIANT_IDS, VARIANT_IDS[:3]])
def test_real_selector_survives_context_roundtrip_and_uses_all_variants(variants):
    ctx = CallContext(call=_outbound("c_variant_roundtrip"), opened_at=NOW)
    seen = []
    for turn in range(len(variants)):
        ctx.turn = turn
        restored = CallContext.from_dict(ctx.to_dict())
        actual = choose_variant(ctx, "ASK_DOB", variants=variants)
        assert choose_variant(restored, "ASK_DOB", variants=variants) == actual
        seen.append(actual)
    assert set(seen) == set(variants)


def test_static_group_avoids_repeats_even_when_turn_numbers_skip_a_rotation():
    ctx = CallContext(call=_outbound("c_variant_skipped_turns"), opened_at=NOW)
    said = []
    for turn in (1, 4, 7):
        ctx.turn = turn
        restored = CallContext.from_dict(ctx.to_dict())
        text = t.choose_static(ctx, t.ASK_DOB)
        assert t.choose_static(restored, t.ASK_DOB) == text
        said.append(text)
        ctx.record("bot", text)
    assert len(set(said)) == 3


def test_static_group_avoids_consecutive_da_when_another_form_is_available(monkeypatch):
    ctx = CallContext(call=_outbound("c_variant_da"), opened_at=NOW)
    ctx.record("bot", t.HOLD)
    monkeypatch.setattr(t, "choose_variant", lambda ctx, group, **kwargs: "v2")
    assert not t.choose_static(ctx, t.ASK_DOB).startswith("Dạ")


@pytest.mark.parametrize(
    "render,args",
    [
        (t.appointment_summary, (APPOINTMENT,)),
        (t.attendance_readback, (APPOINTMENT,)),
        (t.attendance_reread, (APPOINTMENT,)),
        (t.cancel_readback, (APPOINTMENT,)),
        (t.keep_appointment, (APPOINTMENT,)),
        (t.slot_readback, (SLOTS[0],)),
        (t.slot_offer_readback, (SLOTS[0], "RESCHEDULE")),
    ],
)
def test_fixed_safety_readback_rejects_the_old_alternative_variant(render, args):
    with pytest.raises(SevereFailureBlocked) as failure:
        render(_ctx(), *args, variant="v1")
    assert failure.value.code == OUTPUT_UNREGISTERED


def test_offers_say_same_day_only_when_dates_match_and_use_one_slot_question():
    ctx = _ctx()
    same_day = t.offer_slots(ctx, SLOTS)
    assert same_day.count("thứ Tư ngày 14 tháng 10") == 1
    assert "2 giờ 30 chiều cùng ngày" in same_day
    different = [SLOTS[0], {**SLOTS[1], "starts_at": "2026-10-15T14:30:00+07:00"}]
    other_day = t.offer_slots(ctx, different)
    assert "thứ Tư ngày 14 tháng 10" in other_day and "thứ Năm ngày 15 tháng 10" in other_day
    assert "cùng ngày" not in other_day
    single = t.offer_slots(ctx, [SLOTS[0]])
    assert single.endswith("Anh chị chọn giờ này không ạ?")
    assert "chọn khung nào" not in single


def test_offer_and_silence_composite_stay_under_limit_with_long_dates_and_prefixes():
    from itertools import product

    ctx = _ctx()
    slots = [
        {**SLOTS[0], "starts_at": "2026-10-15T10:30:00+07:00"},
        {**SLOTS[1], "starts_at": "2026-10-19T15:30:00+07:00"},
    ]
    for prefix, variant, invite in product(t.SLOT_PREFIXES, VARIANT_IDS, t.SLOT_INVITES):
        text = t.offer_slots(ctx, slots, prefix, 12, date(2026, 10, 14), invite, variant=variant)
        assert len(t.silence_reprompt(text)) < 300
        assert "10 giờ 30 sáng" in text and "3 giờ 30 chiều" in text
        assert text.count("Dạ") <= 1


def test_real_openings_are_fixed_and_alo_is_greeted_back_without_the_retry():
    bot = create_orchestrator(FakeClinicAPI())
    seen, summaries = set(), set()
    for index in range(40):
        call_id = f"c_variant_opening_{index}"
        opening = bot.start_call(_outbound(call_id))
        seen.add(opening.utterance)
        reply = _run(bot, call_id, ["alo"])
        assert reply.utterance in t.static_choices(t.GREETING_BACK_OUTBOUND)
        assert _context(bot, call_id).failed_understandings == 0
        assert _context(bot, call_id).identity_retries == {}
        summary = _run(bot, call_id, ["Nguyễn Văn A", "14/03/1978"], start=2)
        assert summary.state == "AWAITING_INTENT"
        assert summary.utterance.endswith(t.ASK_ATTENDANCE)
        summaries.add(summary.utterance)
    assert seen == set(t.static_choices(t.GREETING_OUTBOUND))
    assert len(summaries) == 1
    assert len(seen) == 1


def test_catalog_has_three_registered_short_safe_forms_and_freezes_safety():
    for original, choices in t.STATIC_VARIANTS.items():
        assert len(set(choices)) == 3
        assert choices[0] == original
        for text in choices:
            assert text in STATIC_UTTERANCES
            assert STATIC_UTTERANCES[text].success_outcome is None
            assert len(text) < 300
            assert not any(secret in text.lower() for secret in ("1978", "nguyễn văn a", "9 giờ"))
    for text in (t.CANCEL_RECONFIRM, t.CANCEL_CHOICE, t.CANCEL_REASON_NOTED, *t.DONE_SAFE.values()):
        if text == t.GOODBYE_UNREACHABLE:
            continue  # closing has three forms, transfer is fixed
        assert t.static_choices(text) == (text,)


@pytest.mark.parametrize(
    "render,ending",
    [
        (t.appointment_summary, t.ASK_ATTENDANCE),
        (t.attendance_readback, "Anh chị đồng ý chứ ạ?"),
        (t.attendance_reread, t.ASK_ATTENDANCE),
        (t.keep_appointment, t.ASK_ATTENDANCE),
        (t.cancel_readback, t.CANCEL_RECONFIRM),
    ],
)
def test_fixed_attendance_readbacks_are_guarded_and_have_the_same_facts(render, ending):
    ctx, ledger = _ctx(), []
    with bind_ledger(ledger):
        text = render(ctx, APPOINTMENT)
    assert "Nội tổng quát" in text
    assert t.attendance_facts(APPOINTMENT) in text
    assert text.endswith(ending) and len(text) <= 300
    action = _ask(ctx, QuestionId.CONFIRM_READBACK, text, action="CONFIRM")
    assert _check(action, ctx, ledger=ledger).ok

    # Modifier cannot rewrite the factual part while keeping a valid render record.
    forged = replace(action, utterance=text.replace("9 giờ", "10 giờ"))
    assert not _check(forged, ctx, ledger=ledger).ok
    with pytest.raises(SevereFailureBlocked) as failure:
        render(_ctx(verified=False), APPOINTMENT)
    assert failure.value.code == "SF-03"


@pytest.mark.parametrize("action_name", ["BOOK", "RESCHEDULE"])
@pytest.mark.parametrize("render", [t.slot_readback, t.slot_offer_readback])
def test_fixed_slot_readback_keeps_selected_slot_and_consent(action_name, render):
    ctx, ledger = _ctx(), []
    ctx.pending_action = action_name
    ctx.selected_slot_id = SLOTS[0]["slot_id"]
    with bind_ledger(ledger):
        text = render(ctx, SLOTS[0], action_name)
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
    assert normal.startswith(t.SLOT_TAKEN) and normal.count("Dạ") == 0
    assert "Còn 3 khung khác." in normal
    assert "Thứ Ba ngày 13 tháng 10 đã kín lịch" in full
    assert invited.endswith("Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ?")
    for text in (normal, full, invited):
        assert "khung 1: 10 giờ sáng" in text and "khung 2: 2 giờ 30 chiều" in text
        assert len(text) <= 300


def test_confirm_after_repeat_silence_and_worker_restart_writes_once(variant):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(_outbound("c_variant_confirm"))
    readback = _run(bot, "c_variant_confirm", ["Nguyễn Văn A", "14/03/1978"])
    assert readback.utterance == t.appointment_summary(
        _context(bot, "c_variant_confirm"), clinic.appointments["apt_00417"]
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
    # Lịch đọc lại theo biến thể, câu hỏi xác nhận hủy giữ nguyên văn
    assert asked.utterance.endswith(t.CANCEL_RECONFIRM) and clinic.writes == []
    assert t.attendance_facts(APPOINTMENT) in asked.utterance
    clarified = _run(bot, "c_variant_cancel", ["vâng"], start=4)
    assert clarified.utterance == t.CANCEL_CHOICE and clinic.writes == []
    done = _run(bot, "c_variant_cancel", ["hủy lịch giúp tôi"], start=5)
    assert done.outcome == "CANCELLED"
    assert len(clinic.writes) == 1


def test_slot_paging_and_confirmation_write_only_the_selected_slot(variant):
    clinic, bot, page = _call("c_variant_slot", "Tôi đổi sang buổi chiều được không?")
    assert page.state == "OFFERING_SLOTS" and "Còn 4 khung khác" in page.utterance
    readback = _say(bot, "c_variant_slot", "khung 2 được không")
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
