"""Mọi câu bot có thể nói phải < 300 ký tự (PRD; Vbee từ chối > 300 là `text_too_long`).

Câu dài hơn không lỗi ở Engine mà ở TTS: không có provider dự phòng thì lượt trả 503 / LiveKit im
lặng. Quét toàn registry thay vì vài fixture: mọi câu tĩnh, mọi renderer trên toàn bộ lịch/slot seed
của Clinic Mock x mọi cơ sở, cộng ngày giờ dài nhất có thể đọc ra, và câu nhắc im lặng ghép với
từng câu. Renderer mới chưa khai báo miền dữ liệu ở đây làm test fail.
"""

from datetime import date
from functools import cache
from itertools import permutations, product
from types import SimpleNamespace

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.variants import VARIANT_IDS
from callbot.engine.policy.utterances import RENDERERS, STATIC_UTTERANCES
from callbot.engine.tools.normalize import normalize_slot
from clinic_mock_sim import FakeClinicAPI

LIMIT = 300
# Renderer chỉ đọc ctx để assert đã xác minh danh tính
VERIFIED = SimpleNamespace(identity_verified=True)
# Chuỗi ngày giờ dài nhất: "12 giờ 45 chiều, Chủ nhật ngày 27 tháng 12"
LONGEST_MOMENT = "2026-12-27T12:45:00+07:00"
LONGEST_DAY = date(2026, 12, 27)
ACTIONS = sorted(t.SLOT_ACTIONS)
DAYS = (None, LONGEST_DAY)


def _domain() -> tuple[list[dict], list[dict]]:
    mock = FakeClinicAPI.mentor_mock()
    seeds = list(mock.appointments.values())
    longest_department = max(seeds, key=lambda a: len(a.get("department") or ""))
    appointments = [
        {**a, "clinic_id": clinic}
        for a in [*seeds, {**longest_department, "starts_at": LONGEST_MOMENT}]
        for clinic in t.CLINIC_NAMES
    ]
    raw = [normalize_slot(s) for s in mock.slots]
    slots = [
        {**s, "clinic_id": clinic}
        for s in [*raw, {**raw[0], "slot_id": "slot_longest", "starts_at": LONGEST_MOMENT}]
        for clinic in t.CLINIC_NAMES
    ]
    return appointments, slots


def _offer_slot_lists(slots: list[dict]) -> list[list[dict]]:
    # offer_slots không đọc cơ sở: mỗi khung một lần, mọi cặp có thứ tự (cùng ngày / khác ngày)
    unique = list({s["slot_id"]: s for s in slots}.values())
    return [[s] for s in unique] + [list(pair) for pair in permutations(unique, 2)]


@cache
def rendered() -> dict[str, list[str]]:
    appointments, slots = _domain()
    by_appointment = {
        "APPOINTMENT_SUMMARY": t.appointment_summary,
        "ATTENDANCE_READBACK": t.attendance_readback,
        "ATTENDANCE_REREAD": t.attendance_reread,
        "CANCEL_READBACK": t.cancel_readback,
        "KEEP_APPOINTMENT": t.keep_appointment,
        "CURRENT_TIME_CHOICE": t.current_time_choice,
        "CONFIRMED_DONE": t.confirmed,
    }
    texts = {
        key: [render(VERIFIED, a) for a in appointments] for key, render in by_appointment.items()
    }
    texts["OFFER_SLOTS"] = [
        t.offer_slots(VERIFIED, offered, prefix, remaining, full_date, invite, variant=variant)
        for offered, prefix, remaining, full_date, invite, variant in product(
            _offer_slot_lists(slots), t.SLOT_PREFIXES, (0, 12), DAYS, t.SLOT_INVITES, VARIANT_IDS
        )
    ]
    texts["ASK_DATE_AGAIN"] = [
        t.ask_date_again(VERIFIED, issue, action, day)
        for issue, action, day in product(sorted(t.DATE_ISSUES), ACTIONS, DAYS)
    ]
    texts["SLOT_OFFER_READBACK"] = [
        t.slot_offer_readback(VERIFIED, slot, action, prefix, full_date)
        for slot, action, prefix, full_date in product(slots, ACTIONS, t.SLOT_PREFIXES, DAYS)
    ]
    texts["SLOT_READBACK"] = [t.slot_readback(VERIFIED, s, a) for s, a in product(slots, ACTIONS)]
    texts["SLOT_READBACK_DA"] = [
        t.slot_readback_da(VERIFIED, s, a) for s, a in product(slots, ACTIONS)
    ]
    texts["CANCELLED_DONE"] = [t.cancelled_done()]
    texts["RESCHEDULED_DONE"] = [t.rescheduled_done(VERIFIED, s) for s in slots]
    texts["BOOKED_DONE"] = [t.booked_done(VERIFIED, s) for s in slots]
    # Câu đang chờ có thể là bất kỳ câu nào bot vừa hỏi: ghép với mọi câu tĩnh và mọi câu render
    pending = [*STATIC_UTTERANCES, *(text for group in texts.values() for text in group)]
    texts["SILENCE_REPROMPT"] = [t.silence_reprompt(text) for text in pending]
    return texts


def _too_long(texts: list[str]) -> list[str]:
    return sorted({text for text in texts if len(text) >= LIMIT}, key=len, reverse=True)[:3]


def test_every_renderer_has_a_declared_length_domain():
    assert set(rendered()) == set(RENDERERS)


def test_every_static_utterance_is_under_the_limit():
    assert not _too_long(list(STATIC_UTTERANCES))


def test_every_rendered_utterance_and_silence_reprompt_is_under_the_limit():
    texts = rendered()
    too_long = {key: _too_long(group) for key, group in texts.items() if _too_long(group)}
    assert not too_long, too_long
    # Miền dữ liệu đủ rộng để chạm các nhánh dài nhất (2 khung + prefix + kín lịch + lời mời)
    assert max(len(text) for text in texts["OFFER_SLOTS"]) > 200
    assert any("12 giờ 45 chiều, Chủ nhật ngày 27 tháng 12" in x for x in texts["BOOKED_DONE"])
