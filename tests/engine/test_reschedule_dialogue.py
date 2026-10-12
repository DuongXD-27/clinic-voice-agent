"""T-10 bước 1–3: Hình 0, tối đa 2 khung mỗi lượt, từ chối không bỏ đổi lịch, đồng ý ở câu chốt.

Dữ liệu giống Clinic Mock deploy (plan T-10 Phụ lục A): lịch cũ 8 giờ sáng 15/10, 11 khung trống
14–21/10, không có khung thứ 7 / chủ nhật.
"""

from datetime import datetime

import pytest

from callbot.engine import CallStart
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction.schema import VN_TZ, Intent, QuestionId
from callbot.engine.extraction.semantic import ReplyKind, SemanticOutcome
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_orchestrator import _context, _inbound, _run, create_orchestrator

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=VN_TZ)  # thứ ba
VERIFY = {"full_name": "Trần Thị Bình", "dob": "1990-06-21"}
SLOTS = [
    ("slot_91d2", "2026-10-14T15:00"),
    ("slot_b501", "2026-10-15T10:30"),
    ("slot_b502", "2026-10-15T15:30"),
    ("slot_b503", "2026-10-16T09:00"),
    ("slot_b504", "2026-10-16T14:00"),
    ("slot_b505", "2026-10-19T10:00"),
    ("slot_b506", "2026-10-19T15:30"),
    ("slot_b507", "2026-10-20T08:00"),
    ("slot_b508", "2026-10-20T14:00"),
    ("slot_b509", "2026-10-21T09:00"),
    ("slot_b510", "2026-10-21T15:00"),
]
AFTERNOON = ["slot_91d2", "slot_b502", "slot_b504", "slot_b506", "slot_b508", "slot_b510"]


def _call(call_id: str, request: str, *, semantic=None):
    clinic = FakeClinicAPI(seed=False, strict_slot_window=True)  # lọc from/to như mock thật
    clinic.seed_patient({"patient_id": "pt_3401", "phone": "0901234501", "verify": VERIFY})
    clinic.seed_appointment(
        {
            "appointment_id": "apt_00418",
            "status": "SCHEDULED",
            "clinic_id": "cl_vinmec",
            "starts_at": "2026-10-15T08:00:00+07:00",
            "ends_at": "2026-10-15T08:30:00+07:00",
            "department": "Nội tổng quát",
            "patient": {"patient_id": "pt_3401", "display_name": "T. T. B.", "verify": VERIFY},
        },
        slot_id="slot_a418",
    )
    for slot_id, start in SLOTS:
        clinic.seed_slot(
            {"slot_id": slot_id, "clinic_id": "cl_vinmec", "start_time": f"{start}:00+07:00"}
        )
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00418"))
    _run(bot, call_id, ["Trần Thị Bình", "21 tháng 6 năm 1990"])
    if semantic is not None:
        bot._extractor._semantic = semantic
    action = _run(bot, call_id, [request], start=3)
    return clinic, bot, action


def _say(bot, call_id: str, *lines: str):
    return _run(bot, call_id, list(lines), start=_context(bot, call_id).turn + 1)


# --- Bước 1: Hình 0 ---------------------------------------------------------------


@pytest.mark.parametrize("answer", ["Được, đổi giúp tôi.", "vâng", "đổi giúp tôi", "ok"])
def test_one_matching_slot_is_read_back_as_a_yes_no_question(answer: str) -> None:
    clinic, bot, action = _call("c_fig0", "Tôi đổi sang chiều ngày 14 tháng 10 được không?")

    assert action.state == "AWAITING_CONFIRMATION"
    assert action.utterance == (
        "Em còn khung 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị đổi sang giờ đó nhé ạ?"
    )
    assert _context(bot, "c_fig0").selected_slot_id == "slot_91d2" and clinic.writes == []

    action = _say(bot, "c_fig0", answer)
    assert action.outcome == "RESCHEDULED"
    assert action.utterance.startswith("Em đã đổi lịch khám sang 3 giờ chiều, thứ Tư")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


# --- Bước 2: tối đa 2 khung, trang tiếp, không lặp khung đã từ chối ------------------


def test_offers_two_slots_and_says_how_many_remain() -> None:
    _, bot, action = _call("c_two", "Tôi đổi sang buổi chiều được không?")

    assert action.state == "OFFERING_SLOTS"
    assert "Còn 4 khung khác" in action.utterance
    assert _context(bot, "c_two").presented_slot_ids == AFTERNOON[:2]


def test_asking_for_other_slots_reads_the_next_page_then_asks_for_another_day() -> None:
    _, bot, _ = _call("c_more", "Tôi đổi sang buổi chiều được không?")

    pages = []
    for _ in range(3):
        action = _say(bot, "c_more", "khung khác")
        pages.append(_context(bot, "c_more").presented_slot_ids)
    assert pages[:2] == [AFTERNOON[2:4], AFTERNOON[4:6]]
    assert action.utterance == t.SLOT_EXHAUSTED["RESCHEDULE"]
    ctx = _context(bot, "c_more")
    assert ctx.question.question_id is QuestionId.ASK_SLOT_PREFERENCE
    assert ctx.pending_action == "RESCHEDULE" and ctx.failed_understandings == 0

    # Test tay 29-09: đọc hết rồi, khách nêu lại một khung đã nghe — tìm lại được, không "chưa thấy"
    action = _say(
        bot, "c_more", "thế đổi cho tôi sang ngày 2 giờ chiều thứ Sáu ngày 16 tháng 10 đi"
    )
    assert action.state == "AWAITING_CONFIRMATION"
    assert _context(bot, "c_more").selected_slot_id == "slot_b504"
    assert action.utterance == (
        "Em xác nhận đổi lịch sang 2 giờ chiều, thứ Sáu ngày 16 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ?"
    )


def test_asking_for_four_slots_reads_two_and_says_why_then_the_rest() -> None:
    """Test tay 29-09: "cho tôi xem 4 khung khác" -> 2 khung + lý do; "xem nốt 2 khung cuối" -> 2 khung cuối."""
    _, bot, _ = _call("c_count", "tôi muốn đổi sang chiều")

    action = _say(bot, "c_count", "cho tôi xem 4 khung khác")
    assert action.utterance.startswith(
        t.SLOT_TWO_AT_A_TIME + "Hiện còn khung 1: 2 giờ chiều, thứ Sáu"
    )
    assert _context(bot, "c_count").presented_slot_ids == AFTERNOON[2:4]

    action = _say(bot, "c_count", "xem nốt 2 khung cuối")
    assert action.state == "OFFERING_SLOTS" and action.utterance.startswith("Hiện còn")
    assert _context(bot, "c_count").presented_slot_ids == AFTERNOON[4:6]


def test_prefix_does_not_repeat_da() -> None:
    _, _, action = _call("c_nomatch", "đổi sang 7 giờ tối ngày 15 tháng 10")
    assert action.utterance.startswith(t.SLOT_NO_MATCH + "Hiện còn khung 1: ")
    assert action.utterance.count("Dạ") == 0


def test_ordinal_on_the_next_page_picks_from_that_page() -> None:
    _, bot, _ = _call("c_page2", "Tôi đổi sang buổi chiều được không?")
    _say(bot, "c_page2", "khung khác")

    _say(bot, "c_page2", "khung 1 được không")
    assert _context(bot, "c_page2").selected_slot_id == "slot_b504"


def test_ordinal_beyond_the_page_is_not_guessed() -> None:
    _, bot, _ = _call("c_k3", "Tôi đổi sang buổi chiều được không?")

    action = _say(bot, "c_k3", "khung 3")
    assert action.utterance.startswith(t.SLOT_NOT_IN_PAGE)
    ctx = _context(bot, "c_k3")
    assert ctx.selected_slot_id is None and ctx.presented_slot_ids == AFTERNOON[:2]


def test_refusing_the_read_back_offers_the_remaining_slot_not_the_refused_one() -> None:
    clinic, bot, _ = _call("c_other", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_other", "khung 1 được không")

    action = _say(bot, "c_other", "không, khung khác")
    ctx = _context(bot, "c_other")
    assert action.state == "AWAITING_CONFIRMATION" and ctx.selected_slot_id == "slot_b502"
    assert ctx.pending_action == "RESCHEDULE" and ctx.evidence == [] and clinic.writes == []


def test_repeated_refusals_end_instead_of_looping() -> None:
    """V-9: trước đây đọc lại cả danh sách, gồm khung vừa từ chối, và lặp mãi."""
    clinic, bot, _ = _call("c_loop", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_loop", "khung 1 được không", "không, tôi muốn đổi khung khác")
    assert _context(bot, "c_loop").selected_slot_id == "slot_b502"

    action = _say(bot, "c_loop", "không, tôi muốn đổi khung khác")
    assert action.utterance == t.SLOT_EXHAUSTED["RESCHEDULE"]
    assert _context(bot, "c_loop").refused_slot_ids == ["slot_b501", "slot_b502"]
    assert clinic.writes == []


def test_a_new_day_at_the_read_back_starts_a_new_request() -> None:
    _, bot, _ = _call("c_newday", "Tôi muốn đổi sang ngày 14 tháng 10")

    action = _say(bot, "c_newday", "không được, ngày 19 tháng 10 thì sao")
    assert action.state == "OFFERING_SLOTS"
    assert not action.utterance.startswith(t.SLOT_AMBIGUOUS)
    assert _context(bot, "c_newday").presented_slot_ids == ["slot_b505", "slot_b506"]


def test_changing_to_another_read_slot_needs_a_new_confirmation() -> None:
    clinic, bot, _ = _call("c_switch", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_switch", "khung 1 được không")

    _say(bot, "c_switch", "thôi lấy khung 2")
    ctx = _context(bot, "c_switch")
    assert ctx.selected_slot_id == "slot_b502" and ctx.evidence == [] and clinic.writes == []

    _say(bot, "c_switch", "được")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


def test_no_slot_for_the_request_is_said_and_not_counted_as_a_misunderstanding() -> None:
    """Ngày 15/10 còn khung nhưng không có 7 giờ tối: không nói "kín", đọc khung của chính ngày đó."""
    _, bot, action = _call("c_nohour", "đổi sang 7 giờ tối ngày 15 tháng 10")

    assert action.utterance.startswith(
        t.SLOT_NO_MATCH
        + "Hiện còn khung 1: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày."
    )
    assert _context(bot, "c_nohour").failed_understandings == 0


# --- Bước 4: R-29 cửa sổ ngày xin, ngày kín, vòng --------------------------------------


def _starts(ctx) -> list[str]:
    return [slot["starts_at"][:10] for slot in ctx.slots]


def test_requested_day_searches_that_day_plus_seven_days() -> None:
    _, bot, action = _call("c_r29", "Tôi muốn đổi sang ngày 16 tháng 10")

    ctx = _context(bot, "c_r29")
    assert ctx.presented_slot_ids == ["slot_b503", "slot_b504"]
    assert min(_starts(ctx)) >= "2026-10-16" and max(_starts(ctx)) < "2026-10-23"
    assert ctx.slot_round == 1 and action.state == "OFFERING_SLOTS"


def test_full_day_is_said_then_the_nearest_slots_after_it() -> None:
    """GC-RES-02: thứ Bảy 17/10 không có khung -> báo kín, đọc 2 khung gần nhất sau ngày đó."""
    _, bot, action = _call("c_kin", "Tôi muốn đổi sang ngày 17 tháng 10")

    assert action.utterance == (
        "Thứ Bảy ngày 17 tháng 10 đã kín lịch. Gần nhất có khung 1: 10 giờ sáng, thứ Hai ngày 19 tháng 10; khung 2: 3 giờ 30 chiều cùng ngày. Còn 4 khung khác. Anh chị chọn khung nào ạ?"
    )
    ctx = _context(bot, "c_kin")
    assert ctx.failed_understandings == 0 and ctx.slot_round == 1


def test_seven_empty_days_search_further_for_the_earliest_after_the_request() -> None:
    """D-3: 1/10–7/10 trống cả -> tra tiếp, gợi ý 2 khung sớm nhất sau ngày xin; vẫn là vòng 1."""
    clinic, bot, action = _call("c_d3", "Tôi muốn đổi sang ngày 1 tháng 10")

    assert action.utterance.startswith(
        "Thứ Năm ngày 1 tháng 10 đã kín lịch. Gần nhất có khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10; khung 2: 10 giờ 30 sáng, thứ Năm ngày 15 tháng 10."
    )
    assert _context(bot, "c_d3").slot_round == 1 and clinic.slot_reads == 2


def test_third_requested_day_keeps_the_old_appointment_and_transfers() -> None:
    """R-29 / GC-RES-05, D-5a: khách nêu tổng cộng 2 ngày; ngày thứ ba -> PATIENT_REQUEST, không ghi."""
    clinic, bot, action = _call("c_rounds", "Tôi muốn đổi sang ngày 14 tháng 10")
    assert action.state == "AWAITING_CONFIRMATION"  # chỉ 1 khung

    action = _say(bot, "c_rounds", "không được, ngày 19 thì sao")
    assert _context(bot, "c_rounds").slot_round == 2 and action.state == "OFFERING_SLOTS"

    action = _say(bot, "c_rounds", "không, ngày 21 đi")
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "PATIENT_REQUEST"
    assert action.utterance == t.ROUNDS_EXHAUSTED_TRANSFER
    assert [write for write in clinic.writes if write[1] == "RESCHEDULED"] == []
    assert clinic.appointments["apt_00418"]["starts_at"].startswith("2026-10-15T08:00")


def test_other_slots_of_the_same_day_are_not_a_new_round() -> None:
    """D-5b: "khung khác" trong cùng ngày không tính vòng; hết khung ở vòng 2 -> chuyển máy (D-5c)."""
    _, bot, _ = _call("c_same", "Tôi muốn đổi sang ngày 14 tháng 10")
    _say(bot, "c_same", "không")  # khung duy nhất bị từ chối -> hỏi ngày khác
    assert _context(bot, "c_same").question.question_id is QuestionId.ASK_SLOT_PREFERENCE

    _say(bot, "c_same", "ngày 19 tháng 10")
    assert _context(bot, "c_same").slot_round == 2

    action = _say(bot, "c_same", "khung khác")
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "PATIENT_REQUEST"


def test_giving_up_in_the_second_round_transfers_instead_of_keeping_silently() -> None:
    """D-5d: "thôi không đổi" ở vòng 2 -> giữ lịch cũ, chuyển PATIENT_REQUEST (vòng 1 xem test dưới)."""
    clinic, bot, _ = _call("c_giveup2", "Tôi muốn đổi sang ngày 14 tháng 10")
    _say(bot, "c_giveup2", "không được, ngày 19 thì sao")

    action = _say(bot, "c_giveup2", "thôi không đổi nữa")
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "PATIENT_REQUEST"
    assert [write for write in clinic.writes if write[1] == "RESCHEDULED"] == []


def test_suggestions_without_a_time_are_not_a_round() -> None:
    """D-5e: "tôi muốn đổi lịch" -> 2 khung sớm nhất, vòng 0; ngày đầu tiên khách nêu mới là vòng 1."""
    _, bot, _ = _call("c_d1", "Tôi muốn đổi lịch")
    assert _context(bot, "c_d1").slot_round == 0
    _say(bot, "c_d1", "không, ngày 19 thì sao")
    assert _context(bot, "c_d1").slot_round == 1


def test_slots_are_read_from_the_clinic_of_the_appointment() -> None:
    """R-29: cùng cơ sở với lịch hiện tại, không lấy cơ sở cấu hình."""
    clinic = FakeClinicAPI(seed=False, strict_slot_window=True)
    clinic.seed_patient({"patient_id": "pt_3401", "phone": "0901234501", "verify": VERIFY})
    clinic.seed_appointment(
        {
            "appointment_id": "apt_00418",
            "status": "SCHEDULED",
            "clinic_id": "c_001",
            "starts_at": "2026-10-15T08:00:00+07:00",
            "ends_at": "2026-10-15T08:30:00+07:00",
            "department": "Nội tổng quát",
            "patient": {"patient_id": "pt_3401", "display_name": "T. T. B.", "verify": VERIFY},
        },
        slot_id="slot_a418",
    )
    clinic.seed_slot(
        {"slot_id": "slot_vm", "clinic_id": "cl_vinmec", "start_time": "2026-10-16T09:00:00+07:00"}
    )
    clinic.seed_slot(
        {"slot_id": "slot_c1", "clinic_id": "c_001", "start_time": "2026-10-16T14:00:00+07:00"}
    )
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    bot.start_call(CallStart(call_id="c_clinic", direction="outbound", appointment_id="apt_00418"))

    _run(bot, "c_clinic", ["Trần Thị Bình", "21 tháng 6 năm 1990", "đổi sang ngày 16 tháng 10"])

    assert [slot["slot_id"] for slot in _context(bot, "c_clinic").slots] == ["slot_c1"]


def test_never_offers_more_than_two_slots_or_a_slot_outside_get_slots() -> None:
    _, bot, _ = _call("c_inv", "Tôi muốn đổi lịch")
    for line in ["khung khác", "khung khác", "khung 3", "khung khác"]:
        _say(bot, "c_inv", line)
        ctx = _context(bot, "c_inv")
        assert len(ctx.presented_slot_ids) <= 2
        assert set(ctx.presented_slot_ids) <= set(ctx.slot_ids)


# --- Bước 3: đồng ý và từ chối ở câu chốt --------------------------------------------


def _at_read_back(call_id: str):
    # "khung 2" là chọn rõ nên ghi ngay (R-29 v2.1); hỏi lại "khung 2 được không" để tới câu chốt
    clinic, bot, _ = _call(call_id, "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, call_id, "khung 2 được không")
    return clinic, bot


def test_read_back_has_weekday_date_time_and_clinic_but_no_department() -> None:
    _, bot = _at_read_back("c_rb")
    text = _context(bot, "c_rb").question.text
    assert text == (
        "Em xác nhận đổi lịch sang 3 giờ 30 chiều, thứ Năm ngày 15 tháng 10, tại Vinmec Times City. Anh chị đồng ý chứ ạ?"
    )


def test_bare_da_is_not_agreement_and_nudges_to_say_dong_y() -> None:
    clinic, bot = _at_read_back("c_da")

    action = _say(bot, "c_da", "dạ")
    assert clinic.writes == [] and action.state == "AWAITING_CONFIRMATION"
    assert "“đồng ý”" in action.utterance

    action = _say(bot, "c_da", "đồng ý")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


@pytest.mark.parametrize(
    "answer", ["chắc là được", "được không em?", "vâng nhưng để tôi hỏi vợ đã"]
)
def test_unclear_answers_reread_yes_no_without_writing(answer: str) -> None:
    clinic, bot = _at_read_back("c_unclear")
    question = _context(bot, "c_unclear").question.text

    action = _say(bot, "c_unclear", answer)
    assert clinic.writes == [] and action.utterance == question


def test_bare_no_at_read_back_asks_instead_of_guessing() -> None:
    """Q-4, §1.1.5: "không" trần không bỏ việc đổi lịch — hỏi nghe khung khác hay giữ lịch."""
    clinic, bot = _at_read_back("c_bare")

    action = _say(bot, "c_bare", "không")
    ctx = _context(bot, "c_bare")
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"]
    assert ctx.pending_action == "RESCHEDULE" and clinic.writes == []

    action = _say(bot, "c_bare", "khung khác")
    assert _context(bot, "c_bare").selected_slot_id == "slot_b501"


@pytest.mark.parametrize("answer", ["thôi không đổi nữa", "giữ lịch cũ"])
def test_giving_up_keeps_the_old_appointment(answer: str) -> None:
    clinic, bot = _at_read_back("c_keep")

    # PRD R-29 v2.1 (GC-RES-09): giữ lịch cũ, không đổi gì, chuyển PATIENT_REQUEST
    action = _say(bot, "c_keep", answer)
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert action.utterance == t.ROUNDS_EXHAUSTED_TRANSFER
    assert [w[1] for w in clinic.writes] == ["TRANSFERRED"]


def test_keeping_after_the_refuse_choice_keeps_the_old_appointment() -> None:
    clinic, bot = _at_read_back("c_keep2")
    _say(bot, "c_keep2", "không")

    action = _say(bot, "c_keep2", "giữ lịch cũ")
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert [w[1] for w in clinic.writes] == ["TRANSFERRED"]


# --- Bước 5: D-1 chưa nêu thời gian, "nào cũng được" -----------------------------------

D1_OFFER = (
    "Gần nhất có khung 1: 3 giờ chiều, thứ Tư ngày 14 tháng 10; khung 2: "
    "10 giờ 30 sáng, thứ Năm ngày 15 tháng 10. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ?"
)


def test_no_time_reads_the_two_earliest_and_invites_another_day() -> None:
    _, bot, action = _call("c_d1_offer", "Tôi muốn đổi lịch")
    assert action.utterance == D1_OFFER
    assert _context(bot, "c_d1_offer").presented_slot_ids == ["slot_91d2", "slot_b501"]

    action = _say(bot, "c_d1_offer", "khung khác")
    assert action.utterance.startswith("Hiện còn khung 1: 3 giờ 30 chiều, thứ Năm")


def test_any_slot_on_the_page_reads_back_the_earliest_and_still_needs_agreement() -> None:
    clinic, bot, _ = _call("c_any_page", "Tôi muốn đổi lịch")
    action = _say(bot, "c_any_page", "khung nào cũng được")

    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert _context(bot, "c_any_page").selected_slot_id == "slot_91d2"
    assert action.utterance.startswith("Em xác nhận đổi lịch sang 3 giờ chiều, thứ Tư")


def test_any_day_after_exhaustion_is_a_round_and_skips_refused_slots() -> None:
    _, bot, _ = _call("c_any_pref", "Tôi muốn đổi sang ngày 14 tháng 10")
    _say(bot, "c_any_pref", "không")  # khung duy nhất bị từ chối -> hỏi ngày khác
    assert _context(bot, "c_any_pref").question.question_id is QuestionId.ASK_SLOT_PREFERENCE

    action = _say(bot, "c_any_pref", "ngày nào cũng được")
    ctx = _context(bot, "c_any_pref")
    assert ctx.slot_round == 2 and action.state == "OFFERING_SLOTS"
    assert ctx.presented_slot_ids == ["slot_b501", "slot_b502"]  # không đọc lại 14/10 vừa từ chối


def test_inbound_booking_without_a_time_invites_another_day_to_book() -> None:
    """BOOK dùng chung D-1, lời mời theo hành động đặt lịch."""
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(_inbound("c_book_d1"))
    action = _run(bot, "c_book_d1", ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch"])

    assert action.state == "OFFERING_SLOTS"
    assert action.utterance.startswith("Gần nhất có khung 1: ")
    assert action.utterance.endswith("Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ?")


# --- Bước 6: R-30 ngày tương đối, hỏi lại ngày (hôm nay thứ Ba 29/09) --------------------


def test_past_weekday_is_said_and_asked_again_without_a_round() -> None:
    _, bot, action = _call("c_past", "Tôi muốn đổi sang thứ Hai")

    assert action.utterance == (
        "Thứ Hai ngày 28 tháng 9 đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ?"
    )
    ctx = _context(bot, "c_past")
    assert (
        ctx.question.question_id is QuestionId.ASK_SLOT_PREFERENCE
        and action.state == "AWAITING_INTENT"
    )
    assert (
        ctx.pending_action == "RESCHEDULE"
        and ctx.slot_round == 0
        and ctx.failed_understandings == 0
    )

    _say(bot, "c_past", "ngày 16 tháng 10")
    ctx = _context(bot, "c_past")
    assert ctx.presented_slot_ids == ["slot_b503", "slot_b504"] and ctx.slot_round == 1


def test_second_unusable_date_in_a_row_counts_as_not_understood() -> None:
    """D-6: lần đầu không tính §1.1.5, lần thứ hai liên tiếp mới tính."""
    _, bot, _ = _call("c_d6", "Tôi muốn đổi sang thứ Hai")
    action = _say(bot, "c_d6", "hôm qua")
    assert action.utterance.startswith("Thứ Hai ngày 28 tháng 9 đã qua rồi ạ.")
    assert _context(bot, "c_d6").failed_understandings == 1


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "Tôi muốn đổi sang tháng sau",
            "Anh chị muốn đổi sang ngày nào cụ thể ạ?",
        ),
        (
            "đổi sang ngày 31 tháng 9",
            "Ngày đó không có trong lịch ạ. Anh chị muốn đổi sang ngày nào ạ?",
        ),
        (
            "đổi sang thứ Ba",
            "Hôm nay là thứ Ba ngày 29 tháng 9. Anh chị muốn đổi sang hôm nay hay thứ Ba tuần sau ạ?",
        ),
    ],
)
def test_unusable_dates_say_why(request_text: str, expected: str) -> None:
    _, bot, action = _call("c_why", request_text)
    assert action.utterance == expected
    assert _context(bot, "c_why").slot_round == 0


def test_bare_weekday_is_this_week_and_full_days_suggest_the_nearest() -> None:
    """R-30: "thứ Sáu" = thứ Sáu 2/10; không có khung -> báo kín, gợi ý gần nhất (không đoán 16/10)."""
    _, bot, action = _call("c_fri", "đổi sang chiều thứ Sáu")
    assert action.utterance.startswith(
        "Thứ Sáu ngày 2 tháng 10 đã kín lịch. Gần nhất có khung 1: 3 giờ chiều, thứ Tư"
    )


def test_week_after_next_reads_that_week() -> None:
    _, bot, _ = _call("c_wan", "đổi sang tuần sau nữa")
    ctx = _context(bot, "c_wan")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b501"] and ctx.slot_round == 1
    assert min(slot["starts_at"][:10] for slot in ctx.slots) >= "2026-10-12"


# --- Bước 7: rule cho câu nói lệch (plan §3.8.1) -------------------------------------------


def test_nearest_and_latter_pick_from_the_page() -> None:
    """ "cái sau" là khung 2 của trang; chọn rõ như "cái đầu tiên" nên ghi ngay (R-29 v2.1)."""
    clinic, bot, _ = _call("c_near", "Tôi muốn đổi lịch")
    action = _say(bot, "c_near", "lấy cái sau đi")
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b501"})]


def test_busy_at_the_offer_asks_other_slots_or_keep() -> None:
    _, bot, _ = _call("c_busy_offer", "Tôi muốn đổi lịch")
    action = _say(bot, "c_busy_offer", "hôm đó tôi phải đi làm")
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"]
    assert _context(bot, "c_busy_offer").pending_action == "RESCHEDULE"


def test_busy_at_the_read_back_drops_that_slot_without_writing() -> None:
    clinic, bot, _ = _call("c_busy_rb", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_busy_rb", "khung 1 được không")
    action = _say(bot, "c_busy_rb", "dạ hôm đó tôi bận mất rồi")

    ctx = _context(bot, "c_busy_rb")
    assert clinic.writes == [] and "slot_b501" in ctx.refused_slot_ids
    assert action.state != "ENDED" and ctx.pending_action == "RESCHEDULE"


def test_asking_back_at_the_read_back_does_not_switch_slot() -> None:
    """ "sao lại là thứ Sáu" ở câu chốt thứ Tư: hỏi lại câu có/không, không đổi sang khung thứ Sáu."""
    clinic, bot, _ = _call("c_askback", "Tôi muốn đổi lịch")
    _say(bot, "c_askback", "khung 1 được không")  # 3 giờ chiều thứ Tư 14/10
    action = _say(bot, "c_askback", "sao lại là thứ Sáu")

    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert _context(bot, "c_askback").selected_slot_id == "slot_91d2"
    assert action.utterance.startswith("Em xác nhận đổi lịch sang 3 giờ chiều, thứ Tư")


# --- Sửa theo eval reschedule 29-09 (eval/reschedule/cases.csv) -----------------------------------


@pytest.mark.parametrize("answer", ["đổi sang giờ đó", "da"])
def test_eval_readback_answers(answer: str) -> None:
    """R086: "đổi sang giờ đó" là đồng ý; R127: "da" không dấu = "dạ" -> hỏi lại có nhắc "đồng ý"."""
    clinic, bot, _ = _call("c_eval_rb", "Tôi muốn đổi sang ngày 14 tháng 10")
    action = _say(bot, "c_eval_rb", answer)
    if answer == "da":
        assert clinic.writes == [] and "đồng ý" in action.utterance
    else:
        assert action.outcome == "RESCHEDULED"


def test_cannot_go_at_that_time_refuses_the_slot_instead_of_cancelling() -> None:
    """R066: "không đi được giờ này" ở câu chốt không chuyển sang hủy lịch."""
    clinic, bot, _ = _call("c_eval_nogo", "Tôi muốn đổi lịch")
    _say(bot, "c_eval_nogo", "khung 1 được không")
    _say(bot, "c_eval_nogo", "tôi không đi được giờ này")
    ctx = _context(bot, "c_eval_nogo")
    assert ctx.pending_action == "RESCHEDULE" and clinic.writes == []
    assert "slot_91d2" in ctx.refused_slot_ids


def test_bare_no_at_the_refuse_choice_asks_again() -> None:
    """R067: "không" ở câu "nghe khung khác hay giữ lịch cũ" -> hỏi lại câu đó, không "em chưa hiểu".

    Hai lần "không" trần liên tiếp đều UNCLEAR: lần thứ hai mới tính §1.1.5, nên không lặp vô hạn.
    """
    _, bot, _ = _call("c_eval_ab", "Tôi muốn đổi lịch")
    _say(bot, "c_eval_ab", "không")
    action = _say(bot, "c_eval_ab", "không")
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"]
    assert _context(bot, "c_eval_ab").failed_understandings == 1


def test_time_only_choice_matching_one_slot_on_the_page_picks_it() -> None:
    """R135: "3 giờ chiều thứ Tư" khớp 14/10 (vừa đọc) và 21/10 (chưa đọc) -> chọn khung vừa đọc,
    không thành "30/9 đã kín" (R-23 v2.1: chọn rõ nên ghi luôn)."""
    clinic, bot, _ = _call("c_eval_amb", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_amb", "3 giờ chiều thứ Tư")
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


def test_time_only_choice_matching_several_slots_off_the_page_reads_at_most_two() -> None:
    """Trang vừa đọc không có khung khớp: đọc tối đa 2 khung khớp rồi hỏi lại, không tự chọn."""
    _, bot, _ = _call("c_eval_amb2", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_amb2", "2 giờ chiều")
    # Nêu đúng chỗ hai khung khác nhau (review 12-10 B9)
    assert action.utterance.startswith(
        "2 giờ chiều em còn thứ Sáu ngày 16 và thứ Ba ngày 20 tháng 10."
    )
    assert "chọn ngày nào" in action.utterance
    assert _context(bot, "c_eval_amb2").presented_slot_ids == ["slot_b504", "slot_b508"]


def test_bare_weekday_not_on_the_page_follows_r30() -> None:
    """R142: "thứ ba" (hôm nay) không khớp khung vừa đọc -> hỏi hôm nay hay tuần sau (GC-DATE-03)."""
    _, bot, _ = _call("c_eval_tue", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_tue", "thứ ba")
    assert action.utterance.startswith("Hôm nay là thứ Ba ngày 29 tháng 9.")


def test_eval_ordinals_pick_the_second_slot() -> None:
    """R008: "giờ thứ 2" là khung 2 (không phải thứ Hai) — chọn rõ nên ghi luôn (R-29 v2.1)."""
    clinic, bot, _ = _call("c_eval_ord", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_ord", "chọn giờ thứ 2")
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b501"})]


def test_eval_remaining_slot_is_read_back() -> None:
    """R010: "giờ còn lại" là khung kia, nhưng không nêu giờ nên đọc lại để chốt."""
    _, bot, _ = _call("c_eval_rest", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_rest", "cho em giờ còn lại")
    assert action.state == "AWAITING_CONFIRMATION"
    assert _context(bot, "c_eval_rest").selected_slot_id == "slot_b501"


# --- Thứ tự nhánh chọn khung: bận / chọn / yêu cầu mới (30-09) ----------------------------------
# Trang ngày 15/10: khung 1 = 10 giờ 30 (slot_b501), khung 2 = 3 giờ 30 chiều (slot_b502)


@pytest.mark.parametrize(
    ("line", "refused", "left"),
    [
        ("10 giờ rưỡi tôi bận", ["slot_b501"], "slot_b502"),
        ("khung 1 tôi bận", ["slot_b501"], "slot_b502"),
        ("10 giờ 30 thì tôi không đi được", ["slot_b501"], "slot_b502"),
        ("3 giờ rưỡi chiều tôi bận", ["slot_b502", "slot_b506"], "slot_b501"),
        (
            "buổi chiều tôi bận",
            ["slot_b502", "slot_b504", "slot_b506", "slot_b508", "slot_b510"],
            "slot_b501",
        ),
    ],
)
def test_busy_with_a_time_at_the_offer_drops_those_slots(line: str, refused, left: str) -> None:
    """ "10 giờ rưỡi tôi bận" là không nhận khung đó, không phải chọn nó: đọc khung còn lại."""
    clinic, bot, _ = _call("c_busy_time", "Tôi muốn đổi sang ngày 15 tháng 10")
    action = _say(bot, "c_busy_time", line)

    ctx = _context(bot, "c_busy_time")
    assert ctx.refused_slot_ids == refused and ctx.selected_slot_id == left
    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []


@pytest.mark.parametrize("line", ["10 giờ rưỡi tôi bận", "khung 1 thì tôi bận"])
def test_busy_with_another_slot_at_the_read_back_keeps_the_read_back(line: str) -> None:
    """Đang chốt 3 giờ 30, "10 giờ rưỡi tôi bận": bỏ 10 giờ 30, hỏi lại có/không 3 giờ 30."""
    clinic, bot = _at_read_back("c_busy_other")
    action = _say(bot, "c_busy_other", line)

    ctx = _context(bot, "c_busy_other")
    assert ctx.selected_slot_id == "slot_b502" and ctx.refused_slot_ids == ["slot_b501"]
    assert action.utterance.startswith("Em xác nhận đổi lịch sang 3 giờ 30 chiều, thứ Năm")
    assert clinic.writes == []


@pytest.mark.parametrize("line", ["3 giờ rưỡi tôi bận", "chiều tôi bận lắm"])
def test_busy_with_the_read_back_time_drops_it_instead_of_searching_it(line: str) -> None:
    """Đang chốt 3 giờ 30, "3 giờ rưỡi tôi bận": không tra lại 3 giờ 30 và đọc lại khung vừa bận."""
    clinic, bot = _at_read_back("c_busy_same")
    action = _say(bot, "c_busy_same", line)

    ctx = _context(bot, "c_busy_same")
    assert "slot_b502" in ctx.refused_slot_ids and ctx.selected_slot_id is None
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"] and clinic.writes == []


def _at_preference(call_id: str):
    """Hỏi ngày khác sau khi từ chối khung duy nhất 14/10 (vòng 1)."""
    clinic, bot, _ = _call(call_id, "Tôi muốn đổi sang ngày 14 tháng 10")
    _say(bot, call_id, "không")
    assert _context(bot, call_id).question.question_id is QuestionId.ASK_SLOT_PREFERENCE
    return clinic, bot


def test_a_new_day_matching_one_slot_is_a_round() -> None:
    """R-29: "8 giờ sáng ngày 20" khớp đúng 1 khung vẫn là ngày thứ hai; từ chối nữa thì chuyển máy."""
    clinic, bot = _at_preference("c_round_match")
    _say(bot, "c_round_match", "8 giờ sáng ngày 20")
    assert _context(bot, "c_round_match").slot_round == 2

    action = _say(bot, "c_round_match", "không")
    assert action.ended and action.transfer_reason == "PATIENT_REQUEST"
    assert ("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b507"}) not in clinic.writes


@pytest.mark.parametrize("setup", ["offer", "refuse_choice"])
def test_a_day_off_the_page_is_a_new_request_everywhere(setup: str) -> None:
    """Ở câu đọc khung và câu A/B, ngày chưa đọc khớp 1 khung cũng tính vòng (R-29)."""
    if setup == "offer":
        _, bot, _ = _call("c_round_off", "Tôi muốn đổi sang ngày 15 tháng 10")
        rounds = 1
    else:
        _, bot, _ = _call("c_round_off", "Tôi muốn đổi lịch")
        _say(bot, "c_round_off", "khung 1 được không", "không")
        rounds = 0
    _say(bot, "c_round_off", "8 giờ sáng ngày 20")
    ctx = _context(bot, "c_round_off")
    assert ctx.selected_slot_id == "slot_b507" and ctx.slot_round == rounds + 1


def test_bare_weekday_at_the_preference_follows_r30() -> None:
    """ "9 giờ thứ Sáu" là thứ Sáu tuần này (02/10, kín), không phải thứ Sáu 16/10 có khung 9 giờ."""
    _, bot = _at_preference("c_pref_fri")
    action = _say(bot, "c_pref_fri", "9 giờ thứ Sáu")
    assert action.utterance.startswith("Thứ Sáu ngày 2 tháng 10 đã kín lịch.")
    assert _context(bot, "c_pref_fri").selected_slot_id is None


def test_refused_slot_is_not_read_again_for_a_new_request() -> None:
    """V-9: đã không nhận 10 giờ 30 thì "10 giờ rưỡi" không đọc lại khung đó."""
    clinic, bot = _at_read_back("c_v9")
    _say(bot, "c_v9", "khung 1")  # đổi sang chốt 10 giờ 30
    _say(bot, "c_v9", "không")
    action = _say(bot, "c_v9", "10 giờ rưỡi")

    ctx = _context(bot, "c_v9")
    assert action.utterance.startswith(t.SLOT_NO_MATCH)
    assert "slot_b501" not in ctx.presented_slot_ids and ctx.selected_slot_id != "slot_b501"


def test_refused_slot_is_not_picked_at_the_refuse_choice() -> None:
    _, bot, _ = _call("c_v9_ab", "Tôi muốn đổi lịch")
    _say(bot, "c_v9_ab", "khung 1 được không", "không")  # không nhận 3 giờ chiều 14/10
    action = _say(bot, "c_v9_ab", "3 giờ chiều ngày 14")
    assert action.utterance.startswith(t.SLOT_NO_MATCH)
    assert "slot_91d2" not in _context(bot, "c_v9_ab").presented_slot_ids


# --- Khung vừa có người đặt (G-7) ---------------------------------------------------------------


def test_taken_slot_with_nothing_left_still_says_it_was_taken() -> None:
    clinic, bot, _ = _call("c_taken_none", "Tôi muốn đổi sang ngày 14 tháng 10")
    clinic.take_slot("slot_91d2")
    action = _say(bot, "c_taken_none", "đồng ý")
    assert action.utterance == t.SLOT_TAKEN_EXHAUSTED["RESCHEDULE"]
    assert not any(w[1] == "RESCHEDULED" for w in clinic.writes)


def test_taken_slot_in_the_last_round_says_it_was_taken_before_transferring() -> None:
    clinic, bot = _at_preference("c_taken_last")
    _say(bot, "c_taken_last", "8 giờ sáng ngày 20")
    clinic.take_slot("slot_b507")
    action = _say(bot, "c_taken_last", "đồng ý")
    assert action.utterance == t.SLOT_TAKEN_ROUNDS_TRANSFER
    assert action.transfer_reason == "PATIENT_REQUEST"


@pytest.mark.parametrize(
    ("request_text", "pick", "taken", "first_day"),
    [
        (
            "Tôi muốn đổi sang 9 giờ ngày 20 tháng 10",
            "khung 1 được không",
            "slot_b507",
            "20 tháng 10",
        ),
        ("Tôi muốn đổi sang ngày 17 tháng 10", "khung 2 được không", "slot_b506", "19 tháng 10"),
    ],
)
def test_taken_slot_searches_again_from_the_requested_day(
    request_text: str, pick: str, taken: str, first_day: str
) -> None:
    """Ngày xin không đúng giờ / đã kín: đề xuất lại vẫn tìm từ ngày xin, không quay về 14/10."""
    clinic, bot, _ = _call("c_taken_day", request_text)
    _say(bot, "c_taken_day", pick)
    clinic.take_slot(taken)
    action = _say(bot, "c_taken_day", "đồng ý")

    assert action.utterance.startswith(t.SLOT_TAKEN)
    assert f"ngày {first_day};" in action.utterance and "14 tháng 10" not in action.utterance


# --- PRD v2.1 R-23 / R-29: chọn rõ khung vừa đọc thì ghi ngay -----------------------------------


@pytest.mark.parametrize(
    "answer", ["Vâng, ba giờ chiều được", "3 giờ chiều", "Đúng rồi, 15 giờ", "cái đầu tiên"]
)
def test_explicit_pick_of_an_offered_slot_reschedules_at_once(answer: str) -> None:
    """GC-RES-03: không hỏi thêm "đồng ý chứ ạ?", đúng một lệnh ghi ở lượt chọn."""
    clinic, bot, action = _call("c_v21_pick", "Tôi đổi sang buổi chiều được không?")
    assert _context(bot, "c_v21_pick").presented_slot_ids == AFTERNOON[:2]

    action = _say(bot, "c_v21_pick", answer)

    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


# --- PRD R-44: tự sửa khi chọn / chốt khung ---------------------------------------------------


def test_corrected_date_in_request_uses_the_last_day() -> None:
    _, bot, action = _call("c_r44_req", "Tôi đổi sang thứ Sáu ngày 17 à không 16 được không?")
    assert action.state == "OFFERING_SLOTS"
    assert _context(bot, "c_r44_req").presented_slot_ids == ["slot_b503", "slot_b504"]


def test_corrected_day_when_choosing_among_offered_slots() -> None:
    _, bot, _ = _call("c_r44_pick", "Tôi đổi sang buổi chiều được không?")
    action = _say(bot, "c_r44_pick", "ngày 14 à không 15")
    assert "ngày 14" not in action.utterance
    # Trang buổi chiều vừa đọc có đúng một khung ngày 15 (15:30): chọn khung đó (review 12-10 B7),
    # không mời lại khung sáng 15/10 trái với "buổi chiều" khách đã xin
    ctx = _context(bot, "c_r44_pick")
    assert ctx.selected_slot_id == "slot_b502"
    assert "3 giờ 30 chiều, thứ Năm ngày 15 tháng 10" in action.utterance


def test_correction_at_readback_is_not_a_refusal_and_later_yes_writes() -> None:
    """ "3 giờ rưỡi, à không, 3 giờ" nhắc lại đúng khung đang chốt: hỏi lại có/không, không bỏ khung."""
    clinic, bot, _ = _call("c_r44_readback", "Tôi đổi sang chiều ngày 14 tháng 10 được không?")
    action = _say(bot, "c_r44_readback", "3 giờ rưỡi, à không, 3 giờ")
    ctx = _context(bot, "c_r44_readback")
    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert ctx.selected_slot_id == "slot_91d2" and "slot_91d2" not in ctx.refused_slot_ids

    action = _say(bot, "c_r44_readback", "vâng")
    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


@pytest.mark.parametrize(
    "answer", ["dạ", "chắc là 3 giờ chiều", "3 giờ chiều à?", "3 giờ chiều thì tôi phải hỏi vợ"]
)
def test_unclear_pick_is_read_back_without_writing(answer: str) -> None:
    """GC-RES-04: mơ hồ thì không ghi, hỏi lại."""
    clinic, bot, _ = _call("c_v21_unclear", "Tôi đổi sang buổi chiều được không?")

    action = _say(bot, "c_v21_unclear", answer)

    assert not action.ended and clinic.writes == []


def test_agreeing_with_the_readback_while_restating_its_time_writes() -> None:
    """GC-RES-03: bot đọc lại khung 3 giờ chiều, khách "Đúng rồi, 15 giờ" -> ghi ngay."""
    clinic, bot, action = _call("c_v21_readback", "Tôi đổi sang chiều ngày 14 tháng 10 được không?")
    assert action.state == "AWAITING_CONFIRMATION"

    action = _say(bot, "c_v21_readback", "Đúng rồi, 15 giờ")

    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


def test_correction_mixed_with_agreement_is_not_a_write_but_the_next_yes_is() -> None:
    """confirmation_veto giữ nguyên: "..., à không, ..., đồng ý" chưa ghi; "vâng" lượt sau mới ghi."""
    clinic, bot, _ = _call("c_r44_veto", "Tôi đổi sang chiều ngày 14 tháng 10 được không?")
    action = _say(bot, "c_r44_veto", "3 giờ rưỡi, à không, 3 giờ, đồng ý")
    assert not action.ended and clinic.writes == []
    action = _say(bot, "c_r44_veto", "vâng")
    assert action.outcome == "RESCHEDULED"


# --- Bench W4: nêu giờ khác ở câu đọc lại lịch, nhận khung thay thế, "thì thôi" ----------------


@pytest.mark.parametrize(
    "request_text, answer",
    [
        ("Đổi cho tôi sang 5 giờ chiều ngày 14", "Không có thì 3 giờ cũng được"),  # rs-02
        ("Cho tôi ba giờ kém mười lăm chiều ngày 14", "Thế ba giờ cũng được"),  # rs-04
        ("Sáng mai khoảng 9 giờ có được không?", "Vậy 3 giờ chiều ngày 14 cũng được"),  # rs-03
        ("Chuyển giúp chị qua 5 giờ chiều ngày 14", "Nếu không còn 5 giờ thì 3 giờ cũng được"),
        ("Tôi muốn 4 giờ chiều ngày 14", "Hết giờ đó rồi thì lấy 3 giờ chiều"),
    ],
)
def test_other_time_then_accepting_an_offered_slot_writes(request_text: str, answer: str) -> None:
    """Nêu giờ khác lịch đang đọc là muốn đổi; giờ đó không có thì nhận khung bot đọc -> ghi ngay."""
    clinic, bot, action = _call("c_bench_alt", request_text)
    assert action.state == "OFFERING_SLOTS" and clinic.writes == []

    action = _say(bot, "c_bench_alt", answer)

    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


class _ModelDown:
    """Tầng ngữ nghĩa timeout ở mọi lượt được gọi."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, context):
        self.calls += 1
        raise TimeoutError("model slow")


@pytest.mark.parametrize(
    "request_text",
    [
        "Sáng mai khoảng 9 giờ có được không?",
        "Cho tôi ba giờ kém mười lăm chiều ngày 14",
        "Chiều thứ Sáu tầm 2 giờ được không em",
        "Có 4 giờ chiều ngày 16 không em",
    ],
)
def test_other_time_still_offers_slots_when_the_model_times_out(request_text: str) -> None:
    """Giờ khác lịch đang đọc nhận ra bằng luật thời gian; model lỗi không biến câu thành hỏi lại xác nhận.
    Lượt này chỉ đọc khung giờ, không ghi gì."""
    down = _ModelDown()
    clinic, bot, action = _call("c_model_down_alt", request_text, semantic=down)
    assert action.state == "OFFERING_SLOTS" and clinic.writes == []
    assert action.utterance != t.CONFIRM_CONFLICT


@pytest.mark.parametrize(
    "answer",
    ["8 giờ sáng ngày 15 ạ", "Hôm đó 9 giờ tôi bận", "Ờ để tôi xem", "Chắc là được 8 giờ"],
)
def test_without_a_new_time_a_model_timeout_still_asks_the_confirmation_again(answer: str) -> None:
    """Đợt 1 giữ nguyên: model lỗi thì không ghi, câu không nêu giờ mới vẫn hỏi lại xác nhận."""
    clinic, bot, action = _call("c_model_down_keep", answer, semantic=_ModelDown())
    assert action.state != "OFFERING_SLOTS"
    assert [w for w in clinic.writes if w[1] != "TRANSFERRED"] == []


@pytest.mark.parametrize("answer", ["Vâng, 8 giờ sáng thứ Năm đúng rồi", "8 giờ sáng ngày 15 ạ"])
def test_restating_the_current_appointment_time_is_not_a_reschedule(answer: str) -> None:
    clinic, bot, action = _call("c_bench_same", answer)
    assert action.state != "OFFERING_SLOTS" and clinic.writes[:1] != [
        ("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})
    ]


@pytest.mark.parametrize(
    "answer",
    ["Không có 5 giờ thì thôi", "Thế thì thôi, giữ lịch cũ", "Không được 5 giờ thì để nguyên"],
)
def test_giving_up_when_the_wanted_time_is_missing_keeps_the_old_appointment(answer: str) -> None:
    """Bỏ đổi lịch dù câu nhắc giờ -> giữ lịch cũ, chuyển PATIENT_REQUEST (GC-RES-09)."""
    clinic, bot, _ = _call("c_bench_giveup", "Tôi muốn đổi lịch")
    _say(bot, "c_bench_giveup", "Không, tôi chỉ đi được 5 giờ chiều thôi")

    action = _say(bot, "c_bench_giveup", answer)

    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "PATIENT_REQUEST"
    assert [w for w in clinic.writes if w[1] == "RESCHEDULED"] == []


def test_resigned_thoi_before_a_time_is_not_giving_up() -> None:
    """ "Thôi, 3 giờ chiều cũng được" là nhận khung, không phải bỏ đổi lịch: đọc lại khung đó."""
    clinic, bot, _ = _call("c_bench_thoi", "Tôi muốn đổi lịch")

    action = _say(bot, "c_bench_thoi", "Thôi, 3 giờ chiều cũng được")

    assert not action.ended and clinic.writes == []
    assert _context(bot, "c_bench_thoi").selected_slot_id == "slot_91d2"


@pytest.mark.parametrize("answer", ["9 giờ hả em?", "Tôi tưởng hẹn 9 giờ chứ?"])
def test_asking_about_a_time_at_the_readback_is_not_a_reschedule(answer: str) -> None:
    clinic, bot, action = _call("c_doubt", answer)
    assert action.state != "OFFERING_SLOTS" and _context(bot, "c_doubt").pending_action is None


def test_dropping_the_change_while_still_picking_an_offered_slot_reads_it_back() -> None:
    """ "Thôi khỏi, 3 giờ cũng được" vẫn nhận khung vừa đọc: không bỏ đổi lịch, không chuyển máy."""
    clinic, bot, _ = _call("c_khoi", "Tôi muốn đổi lịch")

    action = _say(bot, "c_khoi", "Thôi khỏi, 3 giờ chiều cũng được")

    assert action.outcome != "TRANSFERRED"


# --- QC qc-w6-02: trộn tiếng Việt – Anh khi đổi lịch -----------------------------------------------


class _ModelReadsCodeSwitchedReschedule:
    """Jev thật (thử 12/10/2026) đọc "anh muốn change lịch" là CHANGE_INTENT / RESCHEDULE; luật intent
    không có từ tiếng Anh. Lượt chọn khung không gọi model (không thuộc câu hỏi ngữ nghĩa)."""

    def __init__(self) -> None:
        self.transcripts: list[str] = []

    def analyze(self, context) -> SemanticOutcome:
        self.transcripts.append(context.transcript)
        return SemanticOutcome(
            ReplyKind.CHANGE_INTENT, intent=Intent.RESCHEDULE, intent_span="anh muốn change lịch"
        )


def test_code_switched_request_then_an_english_clock_pick_reschedules_at_once() -> None:
    """Nguyên văn qc-w6-02: "Ok, 3pm ngày 14 nhé" chọn rõ khung vừa đọc -> ghi ngay (R-29 v2.1)."""
    request = "Em ơi anh muốn change lịch, có slot nào khác không?"
    model = _ModelReadsCodeSwitchedReschedule()
    clinic, bot, action = _call("c_w6_02", request, semantic=model)
    assert action.state == "OFFERING_SLOTS" and clinic.writes == []
    assert _context(bot, "c_w6_02").presented_slot_ids == ["slot_91d2", "slot_b501"]

    action = _say(bot, "c_w6_02", "Ok, 3pm ngày 14 nhé")

    assert action.outcome == "RESCHEDULED"
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]
    assert model.transcripts == [request]
