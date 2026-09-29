"""T-10 bước 1–3: Hình 0, tối đa 2 khung mỗi lượt, từ chối không bỏ đổi lịch, đồng ý ở câu chốt.

Dữ liệu giống Clinic Mock deploy (plan T-10 Phụ lục A): lịch cũ 8 giờ sáng 15/10, 11 khung trống
14–21/10, không có khung thứ 7 / chủ nhật.
"""

from datetime import datetime

import pytest

from callbot.engine import CallStart
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction.schema import VN_TZ, QuestionId
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


def _call(call_id: str, request: str):
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
    action = _run(bot, call_id, ["Trần Thị Bình", "21 tháng 6 năm 1990", request])
    return clinic, bot, action


def _say(bot, call_id: str, *lines: str):
    return _run(bot, call_id, list(lines), start=_context(bot, call_id).turn + 1)


# --- Bước 1: Hình 0 ---------------------------------------------------------------


@pytest.mark.parametrize("answer", ["Được, đổi giúp tôi.", "vâng", "đổi giúp tôi", "ok"])
def test_one_matching_slot_is_read_back_as_a_yes_no_question(answer: str) -> None:
    clinic, bot, action = _call("c_fig0", "Tôi đổi sang chiều ngày 14 tháng 10 được không?")

    assert action.state == "AWAITING_CONFIRMATION"
    assert action.utterance == (
        "Dạ, chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều. Anh chị đổi sang giờ đó nhé ạ?"
    )
    assert _context(bot, "c_fig0").selected_slot_id == "slot_91d2" and clinic.writes == []

    action = _say(bot, "c_fig0", answer)
    assert action.outcome == "RESCHEDULED"
    assert action.utterance.startswith("Dạ, em đã đổi lịch khám sang 3 giờ chiều thứ Tư")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


# --- Bước 2: tối đa 2 khung, trang tiếp, không lặp khung đã từ chối ------------------


def test_offers_two_slots_and_says_how_many_remain() -> None:
    _, bot, action = _call("c_two", "Tôi đổi sang buổi chiều được không?")

    assert action.state == "OFFERING_SLOTS"
    assert "Ngoài ra còn 4 khung khác" in action.utterance
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
        "Dạ, em xác nhận đổi lịch sang 2 giờ chiều thứ Sáu ngày 16 tháng 10 tại Vinmec Times City. "
        "Anh chị đồng ý chứ ạ?"
    )


def test_asking_for_four_slots_reads_two_and_says_why_then_the_rest() -> None:
    """Test tay 29-09: "cho tôi xem 4 khung khác" -> 2 khung + lý do; "xem nốt 2 khung cuối" -> 2 khung cuối."""
    _, bot, _ = _call("c_count", "tôi muốn đổi sang chiều")

    action = _say(bot, "c_count", "cho tôi xem 4 khung khác")
    assert action.utterance.startswith(
        t.SLOT_TWO_AT_A_TIME + "Hiện còn khung 1 là 2 giờ chiều thứ Sáu"
    )
    assert _context(bot, "c_count").presented_slot_ids == AFTERNOON[2:4]

    action = _say(bot, "c_count", "xem nốt 2 khung cuối")
    assert action.state == "OFFERING_SLOTS" and action.utterance.startswith("Dạ, hiện còn")
    assert _context(bot, "c_count").presented_slot_ids == AFTERNOON[4:6]


def test_prefix_does_not_repeat_da() -> None:
    _, _, action = _call("c_nomatch", "đổi sang 7 giờ tối ngày 15 tháng 10")
    assert action.utterance.startswith(t.SLOT_NO_MATCH + "Hiện còn khung 1 là ")
    assert action.utterance.count("Dạ") == 1


def test_ordinal_on_the_next_page_picks_from_that_page() -> None:
    _, bot, _ = _call("c_page2", "Tôi đổi sang buổi chiều được không?")
    _say(bot, "c_page2", "khung khác")

    _say(bot, "c_page2", "khung 1")
    assert _context(bot, "c_page2").selected_slot_id == "slot_b504"


def test_ordinal_beyond_the_page_is_not_guessed() -> None:
    _, bot, _ = _call("c_k3", "Tôi đổi sang buổi chiều được không?")

    action = _say(bot, "c_k3", "khung 3")
    assert action.utterance.startswith(t.SLOT_NOT_IN_PAGE)
    ctx = _context(bot, "c_k3")
    assert ctx.selected_slot_id is None and ctx.presented_slot_ids == AFTERNOON[:2]


def test_refusing_the_read_back_offers_the_remaining_slot_not_the_refused_one() -> None:
    clinic, bot, _ = _call("c_other", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_other", "khung 1")

    action = _say(bot, "c_other", "không, khung khác")
    ctx = _context(bot, "c_other")
    assert action.state == "AWAITING_CONFIRMATION" and ctx.selected_slot_id == "slot_b502"
    assert ctx.pending_action == "RESCHEDULE" and ctx.evidence == [] and clinic.writes == []


def test_repeated_refusals_end_instead_of_looping() -> None:
    """V-9: trước đây đọc lại cả danh sách, gồm khung vừa từ chối, và lặp mãi."""
    clinic, bot, _ = _call("c_loop", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_loop", "khung 1", "không, tôi muốn đổi khung khác")
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
    _say(bot, "c_switch", "khung 1")

    _say(bot, "c_switch", "thôi lấy khung 2")
    ctx = _context(bot, "c_switch")
    assert ctx.selected_slot_id == "slot_b502" and ctx.evidence == [] and clinic.writes == []

    _say(bot, "c_switch", "được")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


def test_no_slot_for_the_request_is_said_and_not_counted_as_a_misunderstanding() -> None:
    """Ngày 15/10 còn khung nhưng không có 7 giờ tối: không nói "kín", đọc khung của chính ngày đó."""
    _, bot, action = _call("c_nohour", "đổi sang 7 giờ tối ngày 15 tháng 10")

    assert action.utterance.startswith(
        t.SLOT_NO_MATCH + "Hiện còn khung 1 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10; "
        "khung 2 là 3 giờ 30 chiều thứ Năm ngày 15 tháng 10."
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
        "Dạ, thứ Bảy ngày 17 tháng 10 đã kín lịch. Gần nhất em còn khung 1 là 10 giờ sáng thứ Hai "
        "ngày 19 tháng 10; khung 2 là 3 giờ 30 chiều thứ Hai ngày 19 tháng 10. Ngoài ra còn 4 khung "
        "khác. Anh chị chọn khung nào ạ?"
    )
    ctx = _context(bot, "c_kin")
    assert ctx.failed_understandings == 0 and ctx.slot_round == 1


def test_seven_empty_days_search_further_for_the_earliest_after_the_request() -> None:
    """D-3: 1/10–7/10 trống cả -> tra tiếp, gợi ý 2 khung sớm nhất sau ngày xin; vẫn là vòng 1."""
    clinic, bot, action = _call("c_d3", "Tôi muốn đổi sang ngày 1 tháng 10")

    assert action.utterance.startswith(
        "Dạ, thứ Năm ngày 1 tháng 10 đã kín lịch. Gần nhất em còn khung 1 là 3 giờ chiều thứ Tư "
        "ngày 14 tháng 10; khung 2 là 10 giờ 30 sáng thứ Năm ngày 15 tháng 10."
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
    clinic, bot, _ = _call(call_id, "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, call_id, "khung 2")
    return clinic, bot


def test_read_back_has_weekday_date_time_and_clinic_but_no_department() -> None:
    _, bot = _at_read_back("c_rb")
    text = _context(bot, "c_rb").question.text
    assert text == (
        "Dạ, em xác nhận đổi lịch sang 3 giờ 30 chiều thứ Năm ngày 15 tháng 10 "
        "tại Vinmec Times City. Anh chị đồng ý chứ ạ?"
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

    action = _say(bot, "c_keep", answer)
    ctx = _context(bot, "c_keep")
    assert ctx.pending_action is None and clinic.writes == []
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK
    assert "8 giờ sáng thứ Năm ngày 15 tháng 10" in action.utterance


def test_keeping_after_the_refuse_choice_keeps_the_old_appointment() -> None:
    clinic, bot = _at_read_back("c_keep2")
    _say(bot, "c_keep2", "không")

    _say(bot, "c_keep2", "giữ lịch cũ")
    ctx = _context(bot, "c_keep2")
    assert ctx.pending_action is None and clinic.writes == []


# --- Bước 5: D-1 chưa nêu thời gian, "nào cũng được" -----------------------------------

D1_OFFER = (
    "Dạ, lịch trống gần nhất có khung 1 là 3 giờ chiều thứ Tư ngày 14 tháng 10; khung 2 là "
    "10 giờ 30 sáng thứ Năm ngày 15 tháng 10. Anh chị chọn khung nào, hoặc muốn đổi sang ngày khác ạ?"
)


def test_no_time_reads_the_two_earliest_and_invites_another_day() -> None:
    _, bot, action = _call("c_d1_offer", "Tôi muốn đổi lịch")
    assert action.utterance == D1_OFFER
    assert _context(bot, "c_d1_offer").presented_slot_ids == ["slot_91d2", "slot_b501"]

    action = _say(bot, "c_d1_offer", "khung khác")
    assert action.utterance.startswith("Dạ, hiện còn khung 1 là 3 giờ 30 chiều thứ Năm")


def test_any_slot_on_the_page_reads_back_the_earliest_and_still_needs_agreement() -> None:
    clinic, bot, _ = _call("c_any_page", "Tôi muốn đổi lịch")
    action = _say(bot, "c_any_page", "khung nào cũng được")

    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert _context(bot, "c_any_page").selected_slot_id == "slot_91d2"
    assert action.utterance.startswith("Dạ, em xác nhận đổi lịch sang 3 giờ chiều thứ Tư")


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
    assert action.utterance.startswith("Dạ, lịch trống gần nhất có khung 1 là ")
    assert action.utterance.endswith("Anh chị chọn khung nào, hoặc muốn đặt vào ngày khác ạ?")


# --- Bước 6: R-30 ngày tương đối, hỏi lại ngày (hôm nay thứ Ba 29/09) --------------------


def test_past_weekday_is_said_and_asked_again_without_a_round() -> None:
    _, bot, action = _call("c_past", "Tôi muốn đổi sang thứ Hai")

    assert action.utterance == (
        "Dạ, thứ Hai ngày 28 tháng 9 đã qua rồi ạ. Anh chị muốn đổi sang ngày nào ạ?"
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
    assert action.utterance.startswith("Dạ, thứ Hai ngày 28 tháng 9 đã qua rồi ạ.")
    assert _context(bot, "c_d6").failed_understandings == 1


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "Tôi muốn đổi sang tháng sau",
            "Dạ, anh chị cho em xin ngày cụ thể ạ. Anh chị muốn đổi sang ngày nào ạ?",
        ),
        (
            "đổi sang ngày 31 tháng 9",
            "Dạ, ngày đó không có trong lịch ạ. Anh chị muốn đổi sang ngày nào ạ?",
        ),
        (
            "đổi sang thứ Ba",
            "Dạ, hôm nay là thứ Ba ngày 29 tháng 9. Anh chị muốn đổi sang hôm nay hay thứ Ba tuần sau ạ?",
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
        "Dạ, thứ Sáu ngày 2 tháng 10 đã kín lịch. Gần nhất em còn khung 1 là 3 giờ chiều thứ Tư"
    )


def test_week_after_next_reads_that_week() -> None:
    _, bot, _ = _call("c_wan", "đổi sang tuần sau nữa")
    ctx = _context(bot, "c_wan")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b501"] and ctx.slot_round == 1
    assert min(slot["starts_at"][:10] for slot in ctx.slots) >= "2026-10-12"


# --- Bước 7: rule cho câu nói lệch (plan §3.8.1) -------------------------------------------


def test_nearest_and_latter_pick_from_the_page() -> None:
    _, bot, _ = _call("c_near", "Tôi muốn đổi lịch")
    action = _say(bot, "c_near", "lấy cái sau đi")
    assert action.state == "AWAITING_CONFIRMATION"
    assert _context(bot, "c_near").selected_slot_id == "slot_b501"


def test_busy_at_the_offer_asks_other_slots_or_keep() -> None:
    _, bot, _ = _call("c_busy_offer", "Tôi muốn đổi lịch")
    action = _say(bot, "c_busy_offer", "hôm đó tôi phải đi làm")
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"]
    assert _context(bot, "c_busy_offer").pending_action == "RESCHEDULE"


def test_busy_at_the_read_back_drops_that_slot_without_writing() -> None:
    clinic, bot, _ = _call("c_busy_rb", "Tôi muốn đổi sang ngày 15 tháng 10")
    _say(bot, "c_busy_rb", "khung 1")
    action = _say(bot, "c_busy_rb", "dạ hôm đó tôi bận mất rồi")

    ctx = _context(bot, "c_busy_rb")
    assert clinic.writes == [] and "slot_b501" in ctx.refused_slot_ids
    assert action.state != "ENDED" and ctx.pending_action == "RESCHEDULE"


def test_asking_back_at_the_read_back_does_not_switch_slot() -> None:
    """ "sao lại là thứ Sáu" ở câu chốt thứ Tư: hỏi lại câu có/không, không đổi sang khung thứ Sáu."""
    clinic, bot, _ = _call("c_askback", "Tôi muốn đổi lịch")
    _say(bot, "c_askback", "khung 1")  # 3 giờ chiều thứ Tư 14/10
    action = _say(bot, "c_askback", "sao lại là thứ Sáu")

    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert _context(bot, "c_askback").selected_slot_id == "slot_91d2"
    assert action.utterance.startswith("Dạ, em xác nhận đổi lịch sang 3 giờ chiều thứ Tư")


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
    _say(bot, "c_eval_nogo", "khung 1")
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


def test_time_only_choice_matching_several_slots_reads_at_most_two() -> None:
    """R135: "3 giờ chiều thứ Tư" khớp 14/10 và 21/10 -> đọc 2 khung khớp, không thành "30/9 đã kín"."""
    _, bot, _ = _call("c_eval_amb", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_amb", "3 giờ chiều thứ Tư")
    assert action.utterance.startswith(t.SLOT_AMBIGUOUS)
    assert _context(bot, "c_eval_amb").presented_slot_ids == ["slot_91d2", "slot_b510"]


def test_bare_weekday_not_on_the_page_follows_r30() -> None:
    """R142: "thứ ba" (hôm nay) không khớp khung vừa đọc -> hỏi hôm nay hay tuần sau (GC-DATE-03)."""
    _, bot, _ = _call("c_eval_tue", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_tue", "thứ ba")
    assert action.utterance.startswith("Dạ, hôm nay là thứ Ba ngày 29 tháng 9.")


@pytest.mark.parametrize(
    ("text", "slot_id"), [("chọn giờ thứ 2", "slot_b501"), ("cho em giờ còn lại", "slot_b501")]
)
def test_eval_ordinals(text: str, slot_id: str) -> None:
    """R008: "giờ thứ 2" là khung 2 (không phải thứ Hai); R010: "giờ còn lại" là khung kia."""
    _, bot, _ = _call("c_eval_ord", "Tôi muốn đổi lịch")
    action = _say(bot, "c_eval_ord", text)
    assert action.state == "AWAITING_CONFIRMATION"
    assert _context(bot, "c_eval_ord").selected_slot_id == slot_id
