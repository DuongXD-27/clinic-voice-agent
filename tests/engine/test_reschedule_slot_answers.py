"""Review luồng đổi lịch 12-10-2026 (`docs/plans/t10-reschedule-review-2026-10-12.md`), PR 2.

Câu trả lời ở câu mời / câu chốt khung: B5 (đồng ý trần), B6 (nhắc lại khung đang chốt), B8 ("cái thứ
năm"), B10 ("không, 5 giờ chiều"), B11 (nêu lại giờ lịch cũ), S021 ("bỏ luôn lịch"), S034 (không dấu).
Cùng harness với PR 1: sim `mentor_mock()`, đồng hồ thứ Hai 12-10-2026 10:00, lịch apt_00417 lúc 15:30
thứ Tư 14/10. Trang đầu là slot_91d2 (14/10 15:00) + b501 (15/10 10:30); trang sau b502 (15/10 15:30) +
b503 (16/10 9:00).
"""

import pytest

from callbot.engine.extraction.schema import QuestionId
from tests.engine.test_orchestrator import _context, _run
from tests.engine.test_reschedule_ambiguity import (
    BOOK_IDENTITY,
    FIRST_PAGE,
    IDENTITY,
    MODES,
    _call,
    _say,
    _slot_writes,
)

# Câu mời một khung ("Em còn khung 3 giờ chiều, thứ Tư ngày 14 tháng 10. Anh chị đổi sang giờ đó nhé
# ạ?") — như ví dụ Reschedule của contract
ONE_SLOT = [*IDENTITY, "Đổi sang chiều thứ 4 được không"]
READ_BACK_FIRST = [*FIRST_PAGE, "khung nào cũng được"]  # câu chốt 91d2


# --- B5: đồng ý trần ở câu mời 2 khung (PRD GC-RES-04, R-23) -------------------------------------


@pytest.mark.parametrize(
    "answer",
    ["được", "đồng ý", "vâng", "ok", "ừ", "dạ", "dạ được", "được em", "được, đổi giúp tôi"],
)
def test_bare_agreement_reads_back_the_first_slot(answer: str) -> None:
    """Chưa biết khách chọn khung nào: không ghi, đọc câu chốt khung 1 rồi hỏi có/không."""
    call_id = f"b5-{answer}"
    clinic, bot = _call(call_id)
    action = _run(bot, call_id, [*FIRST_PAGE, answer])
    ctx = _context(bot, call_id)
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == "slot_91d2"
    assert "3 giờ chiều, thứ Tư ngày 14 tháng 10" in action.utterance
    assert ctx.failed_understandings == 0
    assert _slot_writes(clinic) == []


def test_bare_agreement_then_yes_writes_the_first_slot() -> None:
    clinic, bot = _call("b5-yes")
    lines = [*FIRST_PAGE, "được"]
    _run(bot, "b5-yes", lines)
    action = _say(bot, "b5-yes", ["đúng rồi"], lines)
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


def test_bare_agreement_then_slot_two_reads_back_slot_two() -> None:
    clinic, bot = _call("b5-two")
    lines = [*FIRST_PAGE, "được"]
    _run(bot, "b5-two", lines)
    _say(bot, "b5-two", ["không, khung 2"], lines)
    ctx = _context(bot, "b5-two")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == "slot_b501"
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("answer", ["được không em", "đồng ý không", "không"])
def test_a_question_or_refusal_is_not_bare_agreement(answer: str) -> None:
    clinic, bot = _call(f"b5-not-{answer}")
    _run(bot, f"b5-not-{answer}", [*FIRST_PAGE, answer])
    ctx = _context(bot, f"b5-not-{answer}")
    assert ctx.question.question_id is not QuestionId.SLOT_READBACK
    assert _slot_writes(clinic) == []


def test_booking_bare_agreement_also_reads_back_without_writing() -> None:
    clinic, bot = _call("b5-book", direction="inbound")
    _run(bot, "b5-book", [*BOOK_IDENTITY, "Tôi muốn đặt lịch", "được"])
    ctx = _context(bot, "b5-book")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert _slot_writes(clinic) == []


# --- B6: nhắc lại đúng khung đang chốt là khẳng định rõ (R-23), chỉ đổi lịch ---------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("answer", ["3 giờ chiều", "3 giờ chiều thứ 4", "thứ Tư ngày 14", "ba giờ"])
def test_restating_the_offered_slot_writes_the_reschedule(mode: str, answer: str) -> None:
    call_id = f"b6-{mode}-{answer}"
    clinic, bot = _call(call_id, mode)
    action = _run(bot, call_id, [*ONE_SLOT, answer])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


def test_restating_the_read_back_slot_writes_the_reschedule() -> None:
    clinic, bot = _call("b6-readback")
    action = _run(bot, "b6-readback", [*READ_BACK_FIRST, "3 giờ chiều thứ 4"])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


@pytest.mark.parametrize("answer", ["3 giờ chiều à", "chiều", "3 giờ chiều hả em", "dạ"])
def test_a_question_or_vague_restatement_is_asked_again(answer: str) -> None:
    clinic, bot = _call(f"b6-not-{answer}")
    _run(bot, f"b6-not-{answer}", [*ONE_SLOT, answer])
    ctx = _context(bot, f"b6-not-{answer}")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == "slot_91d2"
    assert _slot_writes(clinic) == []


def test_booking_restatement_still_needs_an_explicit_yes() -> None:
    """Đặt lịch PHẢI có xác nhận rõ khung đã chọn (§1.1.10): nhắc lại giờ chỉ hỏi lại."""
    clinic, bot = _call("b6-book", direction="inbound")
    lines = [*BOOK_IDENTITY, "Tôi muốn đặt lịch", "khung nào cũng được", "3 giờ chiều"]
    _run(bot, "b6-book", lines)
    ctx = _context(bot, "b6-book")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert _slot_writes(clinic) == []


# --- B8: "cái thứ N" vượt số khung vừa đọc là thứ trong tuần -------------------------------------


@pytest.mark.parametrize(
    ("answer", "slot_id"),
    [("cái thứ tư", "slot_91d2"), ("cái thứ năm", "slot_b501"), ("cái thứ 5", "slot_b501")],
)
def test_cai_thu_beyond_the_page_is_a_weekday_on_the_page(answer: str, slot_id: str) -> None:
    """Như "thứ 4" / "thứ 5": một khung thứ đó trên trang thì chọn luôn (B7)."""
    clinic, bot = _call(f"b8-{answer}")
    action = _run(bot, f"b8-{answer}", [*FIRST_PAGE, answer])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": slot_id})]


@pytest.mark.parametrize("answer", ["cái thứ 6", "cái thứ sáu"])
def test_cai_thu_off_the_page_looks_up_that_weekday(answer: str) -> None:
    clinic, bot = _call(f"b8-off-{answer}")
    _run(bot, f"b8-off-{answer}", [*FIRST_PAGE, answer])
    ctx = _context(bot, f"b8-off-{answer}")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
    assert ctx.presented_slot_ids == ["slot_b503", "slot_b504"]  # thứ Sáu 16/10
    assert _slot_writes(clinic) == []


def test_cai_thu_hai_within_the_page_is_still_slot_two() -> None:
    clinic, bot = _call("b8-hai")
    action = _run(bot, "b8-hai", [*FIRST_PAGE, "cái thứ hai"])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b501"})]


@pytest.mark.parametrize("answer", ["khung thứ ba", "khung số 3"])
def test_khung_with_a_number_stays_a_slot_number(answer: str) -> None:
    clinic, bot = _call(f"b8-khung-{answer}")
    action = _run(bot, f"b8-khung-{answer}", [*FIRST_PAGE, answer])
    assert "Em vừa đọc hai khung thôi" in action.utterance
    assert _slot_writes(clinic) == []


# --- B10: từ chối trang + xin giờ không có -> không đọc lại trang vừa từ chối --------------------


@pytest.mark.parametrize("mode", MODES)
def test_refusing_the_page_for_a_missing_time_offers_other_slots(mode: str) -> None:
    clinic, bot = _call(f"b10-{mode}", mode)
    action = _run(bot, f"b10-{mode}", [*FIRST_PAGE, "không, 5 giờ chiều"])
    ctx = _context(bot, f"b10-{mode}")
    assert "chưa thấy khung giờ đó" in action.utterance
    assert ctx.presented_slot_ids == ["slot_b502", "slot_b503"]
    assert {"slot_91d2", "slot_b501"} <= set(ctx.refused_slot_ids)
    assert ctx.slot_round == 1
    assert _slot_writes(clinic) == []


def test_refused_page_then_giving_up_transfers_like_qc_rs_08() -> None:
    clinic, bot = _call("b10-rs08")
    lines = [*FIRST_PAGE, "Không, tôi chỉ đi được 5 giờ chiều thôi"]
    _run(bot, "b10-rs08", lines)
    action = _say(bot, "b10-rs08", ["Không có 5 giờ thì thôi"], lines)
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "PATIENT_REQUEST"
    assert _slot_writes(clinic) == []


def test_a_missing_time_without_refusal_still_offers_the_nearest() -> None:
    """Đối chứng: không có "không" thì chưa từ chối trang — đọc khung gần nhất như cũ."""
    clinic, bot = _call("b10-ctrl")
    _run(bot, "b10-ctrl", [*FIRST_PAGE, "5 giờ chiều"])
    ctx = _context(bot, "b10-ctrl")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b501"]
    assert ctx.refused_slot_ids == []


# --- B11: nêu lại giờ lịch cũ ở câu chốt (contract-oracle R011) ----------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("answer", ["3 giờ rưỡi", "3 rưỡi chiều", "3 giờ 30 chiều thứ 4"])
def test_naming_the_current_time_asks_keep_or_other(mode: str, answer: str) -> None:
    call_id = f"b11-{mode}-{answer}"
    clinic, bot = _call(call_id, mode)
    action = _run(bot, call_id, [*READ_BACK_FIRST, answer])
    ctx = _context(bot, call_id)
    assert ctx.question.question_id is QuestionId.SLOT_REFUSE_CHOICE
    assert "3 giờ 30 chiều, thứ Tư ngày 14 tháng 10 là giờ lịch hiện tại" in action.utterance
    assert "giữ lịch cũ hay chọn giờ khác" in action.utterance
    assert ctx.slot_round == 0
    assert _slot_writes(clinic) == []


def test_keep_old_after_current_time_transfers_without_writing() -> None:
    clinic, bot = _call("b11-keep")
    lines = [*READ_BACK_FIRST, "3 giờ rưỡi"]
    _run(bot, "b11-keep", lines)
    action = _say(bot, "b11-keep", ["giữ lịch cũ"], lines)
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "PATIENT_REQUEST"
    assert _slot_writes(clinic) == []


def test_other_time_after_current_time_reads_the_next_page() -> None:
    clinic, bot = _call("b11-other")
    lines = [*READ_BACK_FIRST, "3 giờ rưỡi"]
    _run(bot, "b11-other", lines)
    _say(bot, "b11-other", ["chọn giờ khác"], lines)
    ctx = _context(bot, "b11-other")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
    assert ctx.presented_slot_ids == ["slot_b502", "slot_b503"]


def test_current_time_on_another_day_is_a_new_request() -> None:
    """Đối chứng: "3 giờ rưỡi ngày 15" không phải lịch cũ — tra giờ mới, tính vòng."""
    clinic, bot = _call("b11-day")
    _run(bot, "b11-day", [*READ_BACK_FIRST, "3 giờ rưỡi ngày 15"])
    ctx = _context(bot, "b11-day")
    assert ctx.question.question_id is not QuestionId.SLOT_REFUSE_CHOICE
    assert ctx.slot_round == 1


def test_current_clock_time_while_reading_another_day_is_a_new_request() -> None:
    """Câu chốt khung 15/10: "3 giờ rưỡi" là giờ đó ngày khác lịch cũ — tra giờ mới, không hỏi A/B."""
    clinic, bot = _call("b11-other-day")
    lines = [*READ_BACK_FIRST, "không, khung 2", "3 giờ rưỡi"]  # câu chốt b501 (15/10 10:30)
    _run(bot, "b11-other-day", lines)
    ctx = _context(bot, "b11-other-day")
    assert ctx.question.question_id is not QuestionId.SLOT_REFUSE_CHOICE
    assert "slot_b502" in {*ctx.presented_slot_ids, ctx.selected_slot_id}  # 15/10 15:30


# --- S021: "bỏ luôn lịch" là hủy (vẫn xác nhận lần hai, §1.1.4) ----------------------------------


@pytest.mark.parametrize(
    "answer", ["thôi bỏ luôn lịch khám đó cho tôi", "bỏ luôn lịch khám đó cho tôi"]
)
def test_dropping_the_appointment_switches_to_cancel(answer: str) -> None:
    clinic, bot = _call(f"s021-{answer}")
    action = _run(bot, f"s021-{answer}", [*FIRST_PAGE, answer])
    ctx = _context(bot, f"s021-{answer}")
    assert ctx.question.question_id is QuestionId.CANCEL_RECONFIRM
    assert "muốn hủy lịch khám này" in action.utterance
    assert clinic.writes == []


def test_dropping_the_reschedule_still_keeps_the_old_appointment() -> None:
    clinic, bot = _call("s021-ctrl")
    action = _run(bot, "s021-ctrl", [*FIRST_PAGE, "thôi bỏ đổi lịch"])
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "PATIENT_REQUEST"
    assert _slot_writes(clinic) == []


# --- S034: "cái muộn hơn / sớm hơn" không dấu -----------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "slot_id"), [("lay cai muon hon", "slot_b501"), ("lay cai som hon", "slot_91d2")]
)
def test_unaccented_earlier_or_later_one_reads_that_slot_back(answer: str, slot_id: str) -> None:
    """Câu không dấu không phải chọn rõ ("lay" có thể là "lấy" hay "lây"): đọc câu chốt, không ghi."""
    clinic, bot = _call(f"s034-{answer}")
    _run(bot, f"s034-{answer}", [*FIRST_PAGE, answer])
    ctx = _context(bot, f"s034-{answer}")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == slot_id
    assert _slot_writes(clinic) == []


# --- B16: "chọn lại" — quay lại trang để khách chọn, không hỏi lại có/không -------------------------

# Ca user 12-10: "khung khác" -> trang b502 (15/10 15:30) + b503 (16/10 9:00) -> "cái thứ sáu ấy" -> câu chốt b503
RECHOOSE_READBACK = [*FIRST_PAGE, "khung khác", "cái thứ sáu ấy"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "answer",
    [
        "ừ từ từ tôi muốn chọn lại lịch",
        "tôi muốn chọn lại lịch",
        "cho tôi chọn lại",
        "để tôi chọn lại",
        "chon lai",
    ],
)
def test_rechoosing_at_the_read_back_reads_the_page_again(mode: str, answer: str) -> None:
    call_id = f"b16-{mode}-{answer}"
    clinic, bot = _call(call_id, mode)
    action = _run(bot, call_id, [*RECHOOSE_READBACK, answer])
    ctx = _context(bot, call_id)
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
    assert ctx.presented_slot_ids == ["slot_b502", "slot_b503"]
    assert ctx.selected_slot_id is None
    assert "slot_b503" not in ctx.refused_slot_ids  # vẫn chọn lại được
    assert action.utterance.startswith("Dạ, em đọc lại để anh chị chọn ạ.")
    assert "hoặc muốn đổi sang ngày khác" in action.utterance
    assert ctx.failed_understandings == 0 and ctx.unclear_streak == 0
    assert ctx.slot_round == 0
    assert _slot_writes(clinic) == []


def test_rechoosing_then_picking_writes_the_new_choice() -> None:
    clinic, bot = _call("b16-pick")
    lines = [*RECHOOSE_READBACK, "tôi muốn chọn lại lịch"]
    _run(bot, "b16-pick", lines)
    action = _say(bot, "b16-pick", ["khung 1"], lines)
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


def test_rechoosing_the_same_slot_again_still_works() -> None:
    clinic, bot = _call("b16-same")
    lines = [*RECHOOSE_READBACK, "tôi muốn chọn lại lịch"]
    _run(bot, "b16-same", lines)
    action = _say(bot, "b16-same", ["khung 2"], lines)
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b503"})]


@pytest.mark.parametrize(
    ("answer", "question", "slot_id"),
    [
        ("chọn lại khung 1", QuestionId.SLOT_READBACK, "slot_b502"),
        ("tôi muốn chọn lại ngày 20", QuestionId.OFFER_SLOTS, None),
    ],
)
def test_rechoosing_with_a_slot_or_time_follows_that_content(
    answer: str, question: QuestionId, slot_id
) -> None:
    clinic, bot = _call(f"b16-content-{answer}")
    _run(bot, f"b16-content-{answer}", [*RECHOOSE_READBACK, answer])
    ctx = _context(bot, f"b16-content-{answer}")
    assert ctx.question.question_id is question
    if slot_id is not None:
        assert ctx.selected_slot_id == slot_id
    else:
        assert ctx.slot_round == 1  # yêu cầu thời gian mới (R-29)
    assert _slot_writes(clinic) == []


def test_rechoosing_after_a_one_slot_offer_reads_other_slots_or_asks_another_day() -> None:
    clinic, bot = _call("b16-one")
    action = _run(bot, "b16-one", [*ONE_SLOT, "để tôi chọn lại"])
    ctx = _context(bot, "b16-one")
    assert ctx.selected_slot_id is None
    assert "Dạ, em đọc lại" not in action.utterance  # không có trang nào để đọc lại
    assert ctx.question.question_id in (QuestionId.OFFER_SLOTS, QuestionId.ASK_SLOT_PREFERENCE)
    assert _slot_writes(clinic) == []


def test_rechoosing_at_the_keep_or_other_question_reads_the_page_again() -> None:
    clinic, bot = _call("b16-ab")
    lines = [*FIRST_PAGE, "không", "cho tôi chọn lại"]  # "không" trần -> câu A/B
    _run(bot, "b16-ab", lines)
    ctx = _context(bot, "b16-ab")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b501"]
    assert _slot_writes(clinic) == []


def test_rechoosing_at_the_offer_twice_is_not_an_endless_loop() -> None:
    """Ở câu mời: đọc lại đúng trang đó — lần đầu không tính, nói mãi thì chuyển máy (§1.1.5, như B1)."""
    clinic, bot = _call("b16-offer")
    action = _run(bot, "b16-offer", [*FIRST_PAGE, "tôi muốn chọn lại"])
    ctx = _context(bot, "b16-offer")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b501"]
    assert ctx.failed_understandings == 0
    lines = [*FIRST_PAGE, "tôi muốn chọn lại"]
    for extra in (["cho tôi chọn lại"], ["để tôi chọn lại"]):
        action = _say(bot, "b16-offer", extra, lines)
        lines = [*lines, *extra]
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "NOT_UNDERSTOOD"
    assert _slot_writes(clinic) == []


def test_choosing_a_new_appointment_at_the_appointment_read_back_offers_slots() -> None:
    """Câu đọc lịch đầu: "tôi muốn chọn lại lịch" là xin đổi lịch, kể cả khi chỉ có luật."""
    clinic, bot = _call("b16-confirm")
    _run(bot, "b16-confirm", [*IDENTITY, "tôi muốn chọn lại lịch"])
    ctx = _context(bot, "b16-confirm")
    assert ctx.pending_action == "RESCHEDULE"
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
